package com.datathon.backend.service;

import com.datathon.backend.config.AppProperties;
import com.datathon.backend.dto.JobStatusResponse;
import com.datathon.backend.entity.JobEntity;
import com.datathon.backend.repository.JobRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.io.File;
import java.net.ConnectException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.Duration;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

@Slf4j
@Service
@RequiredArgsConstructor
public class VideoAnalysisService {

    private static final int MAX_LOGGED_STDERR_CHARS = 4000;
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    private final JobRepository jobRepository;
    private final ObjectMapper objectMapper;
    private final AppProperties props;

    /** Carries a client-safe error code/message out of the two analysis runners. */
    private static class AnalysisFailure extends RuntimeException {
        final String code;
        AnalysisFailure(String code, String message) {
            super(message);
            this.code = code;
        }
    }

    public String createJob() {
        String jobId = UUID.randomUUID().toString();
        jobRepository.save(JobEntity.builder()
                .jobId(jobId)
                .status("processing")
                .createdAt(System.currentTimeMillis())
                .build());
        return jobId;
    }

    public JobEntity getJob(String jobId) {
        return jobRepository.findById(jobId).orElse(null);
    }

    @Async("analysisExecutor")
    public void processVideoAsync(String jobId, File tempVideoFile) {
        try {
            log.info("Starting job {} ({} mode)", jobId, props.usesService() ? "FastAPI service" : "subprocess");

            String outputJson = props.usesService()
                    ? callService(jobId, tempVideoFile)
                    : runProcess(jobId, tempVideoFile);

            JobStatusResponse response = parseCompletedResult(outputJson);
            response.setJobId(jobId);
            response.setStatus("done");
            response.setMode(props.mode());

            JobEntity job = jobRepository.findById(jobId).orElseThrow();
            job.setStatus("done");
            job.setResultJson(objectMapper.writeValueAsString(response));
            jobRepository.save(job);
            log.info("Job {} completed", jobId);

        } catch (AnalysisFailure f) {
            failJob(jobId, f.code, f.getMessage());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            failJob(jobId, "INTERRUPTED", "Analysis was interrupted");
        } catch (Exception e) {
            log.error("Job {} failed", jobId, e);
            failJob(jobId, "PROCESSING_EXCEPTION", "Internal processing error");
        } finally {
            deleteQuietly(tempVideoFile);
        }
    }

    /** Mode 1: ask the long-running FastAPI service (models already in memory). */
    private String callService(String jobId, File video) throws Exception {
        String body = objectMapper.writeValueAsString(Map.of("path", video.getAbsolutePath()));
        HttpRequest request = HttpRequest.newBuilder(URI.create(props.serviceBaseUrl() + "/analyze"))
                .timeout(Duration.ofMinutes(props.timeoutMinutes()))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body))
                .build();

        HttpResponse<String> response;
        try {
            response = HTTP.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (HttpTimeoutException e) {
            log.error("Job {} timed out waiting for the analysis service", jobId);
            throw new AnalysisFailure("TIMEOUT", "Analysis timed out");
        } catch (ConnectException e) {
            log.error("Job {}: analysis service is not reachable at {}", jobId, props.serviceBaseUrl());
            throw new AnalysisFailure("ANALYSIS_UNAVAILABLE", "Analysis service is not available");
        }

        if (response.statusCode() == 504) {
            throw new AnalysisFailure("TIMEOUT", "Анализ не завершён за отведённое время. Вердикта нет.");
        }
        if (response.statusCode() != 200 || response.body() == null || response.body().isBlank()) {
            // Only known worker error codes get a public message. Never relay arbitrary model text.
            if (response.body() != null && response.body().length() <= 16_384) {
                String code = "";
                try {
                    code = objectMapper.readTree(response.body()).path("error").path("code").asText("");
                } catch (Exception ignored) {
                    // Malformed errors fall back to the generic processing failure below.
                }
                if ("incomplete_analysis".equals(code)) {
                    throw new AnalysisFailure("INCOMPLETE_ANALYSIS",
                            "Модель не смогла проверить всю запись. Вердикта нет; попробуйте более короткий фрагмент.");
                }
                if ("analysis_timeout".equals(code)) {
                    throw new AnalysisFailure("TIMEOUT", "Анализ не завершён за отведённое время. Вердикта нет.");
                }
                if ("worker_unavailable".equals(code)) {
                    throw new AnalysisFailure("ANALYSIS_UNAVAILABLE", "Локальная модель недоступна. Проверьте её готовность.");
                }
            }
            log.error("Job {}: analysis service returned HTTP {}", jobId, response.statusCode());
            throw new AnalysisFailure("ANALYSIS_FAILED", "Video analysis failed");
        }
        return response.body();
    }

    /** A failed, partial, or malformed result must never become a successful empty finding. */
    private JobStatusResponse parseCompletedResult(String outputJson) throws Exception {
        JsonNode result = objectMapper.readTree(outputJson);
        if (result == null || !result.isObject() || result.hasNonNull("error")
                || (result.has("status") && !"done".equals(result.path("status").asText()))) {
            throw new AnalysisFailure("INVALID_RESULT", "Сервис не вернул завершённый результат. Повторите анализ.");
        }
        String verdict = result.path("verdict").asText();
        JsonNode events = result.path("violations");
        if (!("violation".equals(verdict) || "no_violation".equals(verdict)) || !events.isArray()
                || ("violation".equals(verdict) != !events.isEmpty())) {
            throw new AnalysisFailure("INVALID_RESULT", "Сервис вернул некорректный результат. Повторите анализ.");
        }
        JsonNode analysis = result.path("analysis");
        if ((analysis.has("complete") && !analysis.path("complete").asBoolean())
                || (analysis.has("timeline_covered") && !analysis.path("timeline_covered").asBoolean())) {
            throw new AnalysisFailure("INCOMPLETE_ANALYSIS", "Анализ записи не завершён. Попробуйте более короткий фрагмент.");
        }
        if (analysis.path("experimental").asBoolean()) {
            JsonNode done = analysis.path("windows_done");
            JsonNode total = analysis.path("windows_total");
            if (!analysis.path("complete").isBoolean() || !analysis.path("complete").asBoolean()
                    || !analysis.path("timeline_covered").isBoolean() || !analysis.path("timeline_covered").asBoolean()
                    || !done.isIntegralNumber() || !total.isIntegralNumber()
                    || !done.canConvertToInt() || !total.canConvertToInt()
                    || total.asInt() <= 0 || done.asInt() != total.asInt()) {
                throw new AnalysisFailure("INCOMPLETE_ANALYSIS", "Анализ записи не завершён. Попробуйте более короткий фрагмент.");
            }
        }
        for (JsonNode event : events) {
            JsonNode timecode = event.path("timecode_sec");
            if (!timecode.isNumber() || !Double.isFinite(timecode.asDouble()) || timecode.asDouble() < 0) {
                throw new AnalysisFailure("INVALID_RESULT", "Сервис не вернул таймкод события. Повторите анализ.");
            }
        }
        return objectMapper.treeToValue(result, JobStatusResponse.class);
    }

    /** Mode 2 (fallback): start a Python process per video. Slower: models are reloaded every time. */
    private String runProcess(String jobId, File video) throws Exception {
        File outFile = File.createTempFile("py_out_", ".json");
        File errFile = File.createTempFile("py_err_", ".log");
        try {
            Process process = new ProcessBuilder(
                    props.pythonCommand(),
                    props.pythonScriptPath(),
                    video.getAbsolutePath())
                    .redirectOutput(outFile)
                    .redirectError(errFile)
                    .start();
            process.getOutputStream().close();

            if (!process.waitFor(props.timeoutMinutes(), TimeUnit.MINUTES)) {
                process.descendants().forEach(ProcessHandle::destroyForcibly);
                process.destroyForcibly();
                log.error("Job {} timed out after {} min", jobId, props.timeoutMinutes());
                throw new AnalysisFailure("TIMEOUT", "Analysis timed out");
            }

            int exitCode = process.exitValue();
            String out = Files.readString(outFile.toPath(), StandardCharsets.UTF_8);
            if (exitCode == 0 && !out.isBlank()) {
                return out;
            }

            String stderr = Files.readString(errFile.toPath(), StandardCharsets.UTF_8);
            if (stderr.length() > MAX_LOGGED_STDERR_CHARS) {
                stderr = stderr.substring(stderr.length() - MAX_LOGGED_STDERR_CHARS);
            }
            log.error("Job {}: python exited with code {}. stderr tail:\n{}", jobId, exitCode, stderr);
            throw new AnalysisFailure("ANALYSIS_FAILED", "Video analysis failed");
        } finally {
            deleteQuietly(outFile);
            deleteQuietly(errFile);
        }
    }

    /** Marks a job as failed. Message is client-visible: keep it generic. */
    public void failJob(String jobId, String code, String message) {
        try {
            JobStatusResponse failed = JobStatusResponse.builder()
                    .jobId(jobId)
                    .status("failed")
                    .mode(props.mode())
                    .error(Map.of("code", code, "message", message != null ? message : "Unknown error"))
                    .build();

            JobEntity job = jobRepository.findById(jobId)
                    .orElseGet(() -> JobEntity.builder().jobId(jobId).createdAt(System.currentTimeMillis()).build());
            job.setStatus("failed");
            job.setResultJson(objectMapper.writeValueAsString(failed));
            jobRepository.save(job);
        } catch (Exception ex) {
            log.error("Failed to save failed status for job {}", jobId, ex);
        }
    }

    private static void deleteQuietly(File f) {
        if (f != null && f.exists() && !f.delete()) {
            f.deleteOnExit();
        }
    }
}
