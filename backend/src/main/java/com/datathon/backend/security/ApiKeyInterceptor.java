package com.datathon.backend.security;

import com.datathon.backend.config.AppProperties;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

@Component
@RequiredArgsConstructor
public class ApiKeyInterceptor implements HandlerInterceptor {

    private final AppProperties props;

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws IOException {
        // CORS preflight requests never carry custom headers
        if (HttpMethod.OPTIONS.matches(request.getMethod())) {
            return true;
        }

        String provided = request.getHeader("X-API-Key");
        if (provided != null && constantTimeEquals(provided, props.apiKey())) {
            return true;
        }

        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.setContentType("application/json");
        response.setCharacterEncoding("UTF-8");
        response.getWriter().write("{\"error\":\"Invalid or missing X-API-Key\"}");
        return false;
    }

    /** Hash both sides first so comparison time doesn't depend on length or content. */
    private static boolean constantTimeEquals(String a, String b) {
        try {
            MessageDigest sha = MessageDigest.getInstance("SHA-256");
            byte[] ha = sha.digest(a.getBytes(StandardCharsets.UTF_8));
            byte[] hb = sha.digest(b.getBytes(StandardCharsets.UTF_8));
            return MessageDigest.isEqual(ha, hb);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}