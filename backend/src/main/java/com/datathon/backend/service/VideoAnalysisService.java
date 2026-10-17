package com.datathon.backend.service;

import com.datathon.backend.config.AppProperties;
import com.datathon.backend.dto.JobStatusResponse;
import com.datathon.backend.entity.JobEntity;
import com.datathon.backend.repository.JobRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

@Slf4j
@Service
@RequiredArgsConstructor
public class VideoAnalysisService {

    private static final int MAX_LOGGED_STDERR_CHARS = 4000;

    private final JobRepository jobRepository;
    private final ObjectMapper objectMapper;
    private final AppProperties props;

    public String createJob() {
        // Full UUID: 8 chars (32 bits) can collide, and save() on an existing id silently overwrites that job
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
        File outFile = null;
        File errFile = null;
        try {
            log.info("Starting job {} for file {}", jobId, tempVideoFile.getName());

            // Redirect to files instead of reading pipes: no deadlock when stderr is large,
            // and waitFor() with a timeout can be used safely.
            outFile = File.createTempFile("py_out_", ".json");
            errFile = File.createTempFile("py_err_", ".log");

            Process process = new ProcessBuilder(
                    props.pythonCommand(),
                    props.pythonScriptPath(),
                    tempVideoFile.getAbsolutePath())
                    .redirectOutput(outFile)
                    .redirectError(errFile)
                    .start();
            process.getOutputStream().close(); // stdin -> EOF so the script can't wait on input

            if (!process.waitFor(props.timeoutMinutes(), TimeUnit.MINUTES)) {
                process.descendants().forEach(ProcessHandle::destroyForcibly);
                process.destroyForcibly();
                log.error("Job {} timed out after {} min", jobId, props.timeoutMinutes());
                failJob(jobId, "TIMEOUT", "Analysis timed out");
                return;
            }

            int exitCode = process.exitValue();
            String outputJson = Files.readString(outFile.toPath(), StandardCharsets.UTF_8);

            if (exitCode == 0 && !outputJson.isBlank()) {
                JobStatusResponse response = objectMapper.readValue(outputJson, JobStatusResponse.class);
                response.setJobId(jobId);
                response.setStatus("done");
                response.setMode(props.mode());

                JobEntity job = jobRepository.findById(jobId).orElseThrow();
                job.setStatus("done");
                job.setResultJson(objectMapper.writeValueAsString(response));
                jobRepository.save(job);

                log.info("Job {} completed", jobId);
            } else {
                String stderr = Files.readString(errFile.toPath(), StandardCharsets.UTF_8);
                if (stderr.length() > MAX_LOGGED_STDERR_CHARS) {
                    stderr = stderr.substring(stderr.length() - MAX_LOGGED_STDERR_CHARS);
                }
                // Details stay in the server log only; the client gets a generic message
                log.error("Job {}: python exited with code {}. stderr tail:\n{}", jobId, exitCode, stderr);
                failJob(jobId, "ANALYSIS_FAILED", "Video analysis failed");
            }

        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            failJob(jobId, "INTERRUPTED", "Analysis was interrupted");
        } catch (Exception e) {
            log.error("Job {} failed", jobId, e);
            failJob(jobId, "PROCESSING_EXCEPTION", "Internal processing error");
        } finally {
            deleteQuietly(tempVideoFile);
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