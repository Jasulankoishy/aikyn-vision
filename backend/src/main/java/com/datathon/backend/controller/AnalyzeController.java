package app.controller;

import app.dto.AnalyzeInitResponse;
import app.dto.JobStatusResponse;
import app.entity.JobEntity;
import app.service.VideoAnalysisService;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import java.io.File;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class AnalyzeController {

    private final VideoAnalysisService analysisService;
    private final ObjectMapper objectMapper;

    @Value("${app.api-key:forte_datathon_secret_key_2026}")
    private String expectedApiKey;

    @Value("${app.mode:real}")
    private String appMode;

    private void validateApiKey(String apiKey) {
        if (apiKey == null || !apiKey.equals(expectedApiKey)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid or missing X-API-Key");
        }
    }

    @PostMapping(value = "/analyze", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<?> analyzeVideo(
            @RequestHeader(value = "X-API-Key", required = false) String apiKey,
            @RequestParam("file") MultipartFile file) {

        validateApiKey(apiKey);

        if (file.isEmpty() || file.getOriginalFilename() == null || !file.getOriginalFilename().toLowerCase().endsWith(".mov")) {
            return ResponseEntity.status(HttpStatus.UNSUPPORTED_MEDIA_TYPE)
                    .body(Map.of("error", "Only .mov video files are allowed"));
        }

        try {
            File tempFile = File.createTempFile("upload_", "_" + file.getOriginalFilename());
            file.transferTo(tempFile);

            String jobId = analysisService.createJob();
            analysisService.processVideoAsync(jobId, tempFile);

            return ResponseEntity.status(HttpStatus.ACCEPTED)
                    .body(AnalyzeInitResponse.builder()
                            .jobId(jobId)
                            .status("processing")
                            .mode(appMode)
                            .build());

        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "Failed to save file"));
        }
    }

    @GetMapping("/jobs/{job_id}")
    public ResponseEntity<?> getJobStatus(
            @RequestHeader(value = "X-API-Key", required = false) String apiKey,
            @PathVariable("job_id") String jobId) {

        validateApiKey(apiKey);

        JobEntity job = analysisService.getJob(jobId);
        if (job == null) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .body(Map.of("error", "Job not found"));
        }

        if ("processing".equals(job.getStatus())) {
            return ResponseEntity.ok(JobStatusResponse.builder()
                    .jobId(jobId)
                    .status("processing")
                    .mode(appMode)
                    .build());
        }

        try {
            JobStatusResponse response = objectMapper.readValue(job.getResultJson(), JobStatusResponse.class);
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "Failed to parse job result"));
        }
    }
}