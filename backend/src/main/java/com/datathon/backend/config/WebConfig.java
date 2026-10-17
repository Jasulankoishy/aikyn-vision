package com.datathon.backend.config;

import com.datathon.backend.security.ApiKeyInterceptor;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
@RequiredArgsConstructor
public class WebConfig implements WebMvcConfigurer {

    private final AppProperties props;
    private final ApiKeyInterceptor apiKeyInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // One place for auth instead of calling validateApiKey() in every method
        registry.addInterceptor(apiKeyInterceptor).addPathPatterns("/api/v1/**", "/readyz");
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/**")
                .allowedOrigins(props.allowedOrigins().toArray(String[]::new))
                .allowedMethods("GET", "POST", "OPTIONS")
                .allowedHeaders("X-API-Key", "Content-Type")
                // No allowCredentials: auth is a header, not a cookie.
                // No exposedHeaders: the API key must never be echoed back.
                .maxAge(3600);
    }

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        // Serves frontend files from classpath:/static/ or the frontend/ folder.
        // Keep secrets (.env, source maps, API keys) out of these folders.
        registry.addResourceHandler("/**")
                .addResourceLocations("classpath:/static/", "file:frontend/", "file:../frontend/");
    }
}