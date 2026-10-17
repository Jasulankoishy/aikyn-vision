package com.datathon.backend.controller;

import com.datathon.backend.config.AppProperties;
import com.datathon.backend.dto.AnalyzeInitResponse;
import com.datathon.backend.dto.JobStatusResponse;
import com.datathon.backend.entity.JobEntity;
import com.datathon.backend.service.VideoAnalysisService;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.task.TaskRejectedException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

@Slf4j
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class AnalyzeController {

    /** First atom type (bytes 4-8) of a QuickTime/MP4 container. Old .mov files may not start with 'ftyp'. */
    private static final Set<String> QUICKTIME_ATOMS =
            Set.of("ftyp", "moov", "mdat", "wide", "free", "skip", "pnot");

    private final VideoAnalysisService analysisService;
    private final ObjectMapper objectMapper;
    private final AppProperties props;

    @PostMapping(value = "/analyze", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<?> analyzeVideo(@RequestParam("file") MultipartFile file) {

        String name = file.getOriginalFilename();
        if (file.isEmpty() || name == null || !name.toLowerCase(Locale.ROOT).endsWith(".mov")) {
            return error(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "Only .mov video files are allowed");
        }

        File tempFile = null;
        String jobId = null;
        boolean handedOff = false; // once true, the async worker owns (and deletes) the temp file

        try {
            // Fixed suffix: never put the user-supplied filename on disk
            tempFile = File.createTempFile("upload_", ".mov");
            file.transferTo(tempFile);

            if (!looksLikeQuickTime(tempFile)) {
                return error(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "File content is not a valid .mov video");
            }

            jobId = analysisService.createJob();
            analysisService.processVideoAsync(jobId, tempFile);
            handedOff = true;

            return ResponseEntity.status(HttpStatus.ACCEPTED)
                    .body(AnalyzeInitResponse.builder()
                            .jobId(jobId)
                            .status("processing")
                            .mode(props.mode())
                            .build());

        } catch (TaskRejectedException e) {
            log.warn("Analysis queue is full, rejecting upload");
            if (jobId != null) {
                analysisService.failJob(jobId, "SERVER_BUSY", "Server is busy, try again later");
            }
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .header(HttpHeaders.RETRY_AFTER, "30")
                    .body(Map.of("error", "Server is busy, try again later"));

        } catch (Exception e) {
            log.error("Failed to accept upload", e);
            return error(HttpStatus.INTERNAL_SERVER_ERROR, "Failed to save file");

        } finally {
            if (!handedOff && tempFile != null) {
                tempFile.delete();
            }
        }
    }

    @GetMapping("/jobs/{job_id}")
    public ResponseEntity<?> getJobStatus(@PathVariable("job_id") String jobId) {

        JobEntity job = analysisService.getJob(jobId);
        if (job == null) {
            return error(HttpStatus.NOT_FOUND, "Job not found");
        }

        if ("processing".equals(job.getStatus())) {
            return ResponseEntity.ok(JobStatusResponse.builder()
                    .jobId(jobId)
                    .status("processing")
                    .mode(props.mode())
                    .build());
        }

        try {
            return ResponseEntity.ok(objectMapper.readValue(job.getResultJson(), JobStatusResponse.class));
        } catch (Exception e) {
            log.error("Failed to parse stored result for job {}", jobId, e);
            return error(HttpStatus.INTERNAL_SERVER_ERROR, "Failed to parse job result");
        }
    }

    private static boolean looksLikeQuickTime(File f) {
        try (InputStream in = new FileInputStream(f)) {
            byte[] header = in.readNBytes(12);
            if (header.length < 12) {
                return false;
            }
            return QUICKTIME_ATOMS.contains(new String(header, 4, 4, StandardCharsets.ISO_8859_1));
        } catch (IOException e) {
            return false;
        }
    }

    private static ResponseEntity<Map<String, String>> error(HttpStatus status, String message) {
        return ResponseEntity.status(status).body(Map.of("error", message));
    }
}