package com.datathon.backend.controller;

import com.datathon.backend.config.AppProperties;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;
import java.util.Map;
import java.util.Set;

/** In-memory connection bootstrap for the desktop launcher, disabled for other deployments. */
@RestController
public class LocalSessionController {
    private static final Set<String> LOOPBACK = Set.of("127.0.0.1", "::1", "[::1]", "0:0:0:0:0:0:0:1");
    private final AppProperties props;
    private final boolean enabled;

    public LocalSessionController(AppProperties props,
                                  @Value("${app.local-bootstrap-enabled:false}") boolean enabled) {
        this.props = props;
        this.enabled = enabled;
    }

    @GetMapping("/local-session")
    public ResponseEntity<?> localSession(HttpServletRequest request) {
        if (!enabled || !isLocalSameOrigin(request)) {
            return ResponseEntity.status(403).cacheControl(CacheControl.noStore())
                    .body(Map.of("error", "Local session is unavailable"));
        }
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .header("Pragma", "no-cache")
                .header("X-Content-Type-Options", "nosniff")
                .body(Map.of("api_key", props.apiKey(), "mode", props.mode()));
    }

    private boolean isLocalSameOrigin(HttpServletRequest request) {
        if (!LOOPBACK.contains(request.getRemoteAddr()) || !LOOPBACK.contains(request.getLocalAddr())
                || !"1".equals(request.getHeader("X-Local-Bootstrap"))
                || !"same-origin".equals(request.getHeader("Sec-Fetch-Site"))) {
            return false;
        }
        try {
            String host = request.getHeader("Host");
            if (host == null || host.contains("/") || host.contains("\\")) return false;
            URI origin = URI.create(request.getScheme() + "://" + host);
            String hostname = origin.getHost();
            if (hostname == null || !(LOOPBACK.contains(hostname) || "localhost".equalsIgnoreCase(hostname))
                    || origin.getRawUserInfo() != null || origin.getRawQuery() != null || origin.getRawFragment() != null) {
                return false;
            }
            int port = origin.getPort() < 0 ? ("https".equals(origin.getScheme()) ? 443 : 80) : origin.getPort();
            if (port != request.getLocalPort()) return false;
            // Fetch Metadata cannot be set by browser JavaScript. Also reject a conflicting Origin.
            String suppliedOrigin = request.getHeader("Origin");
            return suppliedOrigin == null || origin.equals(URI.create(suppliedOrigin));
        } catch (IllegalArgumentException error) {
            return false;
        }
    }
}
