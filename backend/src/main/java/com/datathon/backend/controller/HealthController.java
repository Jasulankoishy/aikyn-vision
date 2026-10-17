package com.datathon.backend.controller;

import com.datathon.backend.config.AppProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

@RestController
@RequiredArgsConstructor
public class HealthController {

    private final AppProperties props;

    @GetMapping("/healthz")
    public ResponseEntity<?> healthz() {
        return ResponseEntity.ok(Map.of("status", "ok"));
    }

    // API key is checked by ApiKeyInterceptor (registered for /readyz)
    @GetMapping("/readyz")
    public ResponseEntity<?> readyz() {
        if (!Files.isRegularFile(Path.of(props.pythonScriptPath()))) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(Map.of(
                    "status", "not_ready",
                    "ready", false,
                    "mode", props.mode(),
                    "error", "Analysis script not found"
            ));
        }
        return ResponseEntity.ok(Map.of(
                "status", "ready",
                "ready", true,
                "mode", props.mode()
        ));
    }
}