package com.datathon.backend.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

import java.util.List;

/**
 * Single place for all app.* settings (replaces the scattered @Value fields).
 * The API key has NO default on purpose: the app refuses to start without one.
 */
@ConfigurationProperties(prefix = "app")
public record AppProperties(
        String apiKey,
        @DefaultValue("real") String mode,
        @DefaultValue("python3") String pythonCommand,
        @DefaultValue("../scripts/analyze.py") String pythonScriptPath,
        @DefaultValue("") String pythonServiceUrl,            // NEW
        @DefaultValue("4") long timeoutMinutes,
        @DefaultValue("24") long jobTtlHours,
        @DefaultValue({"http://localhost:3000", "http://localhost:5173"}) List<String> allowedOrigins
) {
    public AppProperties {
        if (apiKey == null || apiKey.isBlank()) {
            throw new IllegalStateException("app.api-key must be set (use the APP_API_KEY environment variable)");
        }
    }

    // NEW
    public boolean usesService() {
        return pythonServiceUrl != null && !pythonServiceUrl.isBlank();
    }

    // NEW
    public String serviceBaseUrl() {
        return pythonServiceUrl.replaceAll("/+$", "");
    }
}
