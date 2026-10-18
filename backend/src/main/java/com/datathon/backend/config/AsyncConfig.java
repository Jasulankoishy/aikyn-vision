package com.datathon.backend.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

@Configuration
public class AsyncConfig {

    /**
     * Bounded executor: ONE video analysed at a time; configurable waiting capacity (legacy default 10).
     * Must match the Python side (service.py ANALYZE_CONCURRENCY, default 1). With more Java workers than
     * Python slots, the extra video waits inside Python and that wait eats its time budget -> false TIMEOUTs.
     * If you raise ANALYZE_CONCURRENCY for the Python service, raise both numbers below to the same value.
     * Quick local mode sets capacity 0: reject another video instead of exceeding the total wait budget.
     * When the queue is full, submitting throws TaskRejectedException (controller returns 429).
     */
    @Bean(name = "analysisExecutor")
    public ThreadPoolTaskExecutor analysisExecutor(@Value("${app.analysis-queue-capacity:10}") int queueCapacity) {
        if (queueCapacity < 0) {
            throw new IllegalArgumentException("app.analysis-queue-capacity must be nonnegative");
        }
        ThreadPoolTaskExecutor ex = new ThreadPoolTaskExecutor();
        ex.setCorePoolSize(1);
        ex.setMaxPoolSize(1);
        ex.setQueueCapacity(queueCapacity);
        ex.setThreadNamePrefix("analysis-");
        ex.setWaitForTasksToCompleteOnShutdown(false);
        return ex;
    }
}
