package com.datathon.backend.service;

import com.datathon.backend.config.AppProperties;
import com.datathon.backend.repository.JobRepository;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.util.concurrent.TimeUnit;

@Slf4j
@Service
@RequiredArgsConstructor
public class JobMaintenanceService {

    private final JobRepository jobRepository;
    private final VideoAnalysisService analysisService;
    private final AppProperties props;

    /** Jobs still "processing" at startup lost their Python process in the restart: fail them. */
    @PostConstruct
    public void failInterruptedJobs() {
        var stuck = jobRepository.findByStatus("processing");
        stuck.forEach(j -> analysisService.failJob(j.getJobId(), "INTERRUPTED", "Server restarted during analysis"));
        if (!stuck.isEmpty()) {
            log.warn("Marked {} interrupted job(s) as failed", stuck.size());
        }
    }

    /** Hourly cleanup so the DB (which stores base64 frames) doesn't grow forever. */
    @Scheduled(initialDelay = 60_000, fixedDelay = 3_600_000)
    public void purgeOldJobs() {
        long cutoff = System.currentTimeMillis() - TimeUnit.HOURS.toMillis(props.jobTtlHours());
        int removed = jobRepository.deleteOlderThan(cutoff);
        if (removed > 0) {
            log.info("Purged {} job(s) older than {}h", removed, props.jobTtlHours());
        }
    }
}