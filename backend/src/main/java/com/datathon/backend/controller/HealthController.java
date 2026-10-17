package com.datathon.backend.controller;

import com.datathon.backend.config.AppProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.regex.Pattern;

@RestController
@RequiredArgsConstructor
public class HealthController {

    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(2))
            .build();
    private static final Pattern MODEL_LOADED = Pattern.compile("\"model_loaded\"\\s*:\\s*true");

    private final AppProperties props;

    @GetMapping("/healthz")
    public ResponseEntity<?> healthz() {
        return ResponseEntity.ok(Map.of("status", "ok"));
    }

    // API key is checked by ApiKeyInterceptor (registered for /readyz)
    @GetMapping("/readyz")
    public ResponseEntity<?> readyz() {
        String problem = props.usesService() ? checkService() : checkScript();
        if (problem != null) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(Map.of(
                    "status", "not_ready",
                    "ready", false,
                    "mode", props.mode(),
                    "error", problem
            ));
        }
        return ResponseEntity.ok(Map.of(
                "status", "ready",
                "ready", true,
                "mode", props.mode()
        ));
    }

    private String checkScript() {
        Path script = Path.of(props.pythonScriptPath());
        if (!Files.isRegularFile(script)) {
            return "Analysis script not found";
        }
        // engine.py loads model.joblib from the same folder as the scripts
        if (!Files.isRegularFile(script.toAbsolutePath().resolveSibling("model.joblib"))) {
            return "Analysis model not found";
        }
        return null;
    }

    private String checkService() {
        try {
            HttpRequest request = HttpRequest.newBuilder(URI.create(props.serviceBaseUrl() + "/health"))
                    .timeout(Duration.ofSeconds(3))
                    .GET()
                    .build();
            HttpResponse<String> response = HTTP.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() == 200 && MODEL_LOADED.matcher(response.body()).find()) {
                return null;
            }
            return "Analysis service is starting or its model is not loaded";
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return "Analysis service check interrupted";
        } catch (Exception e) {
            return "Analysis service is not reachable";
        }
    }
}