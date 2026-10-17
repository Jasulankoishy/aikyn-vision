package com.datathon.backend.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

@Configuration
public class AsyncConfig {

    /**
     * Bounded executor: ONE video analysed at a time, 10 waiting.
     * Must match the Python side (service.py ANALYZE_CONCURRENCY, default 1). With more Java workers than
     * Python slots, the extra video waits inside Python and that wait eats its time budget -> false TIMEOUTs.
     * If you raise ANALYZE_CONCURRENCY for the Python service, raise both numbers below to the same value.
     * When the queue is full, submitting throws TaskRejectedException (controller returns 503).
     */
    @Bean(name = "analysisExecutor")
    public ThreadPoolTaskExecutor analysisExecutor() {
        ThreadPoolTaskExecutor ex = new ThreadPoolTaskExecutor();
        ex.setCorePoolSize(1);
        ex.setMaxPoolSize(1);
        ex.setQueueCapacity(10);
        ex.setThreadNamePrefix("analysis-");
        ex.setWaitForTasksToCompleteOnShutdown(false);
        return ex;
    }
}