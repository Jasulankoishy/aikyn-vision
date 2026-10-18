package com.datathon.backend;

import com.datathon.backend.config.AppProperties;
import com.datathon.backend.config.AsyncConfig;
import com.datathon.backend.controller.AnalyzeController;
import com.datathon.backend.service.VideoAnalysisService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.core.task.TaskRejectedException;
import org.springframework.mock.web.MockMultipartFile;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class QuickLocalQueueTests {
    @Test
    void zeroQueueRejectsSecondTaskInsteadOfWaitingBehindAnActiveVideo() throws Exception {
        var executor = new AsyncConfig().analysisExecutor(0);
        executor.initialize();
        var started = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        try {
            executor.execute(() -> {
                started.countDown();
                try { release.await(5, TimeUnit.SECONDS); }
                catch (InterruptedException e) { Thread.currentThread().interrupt(); }
            });
            assertTrue(started.await(2, TimeUnit.SECONDS));
            assertThrows(TaskRejectedException.class, () -> executor.execute(() -> {}));
        } finally {
            release.countDown();
            executor.shutdown();
        }
    }

    @Test
    void rejectedUploadReturns429WithoutInventingAResult() {
        var service = mock(VideoAnalysisService.class);
        when(service.createJob()).thenReturn("synthetic-job");
        doThrow(new TaskRejectedException("synthetic busy worker"))
                .when(service).processVideoAsync(eq("synthetic-job"), any());
        var controller = new AnalyzeController(service, new ObjectMapper(), mock(AppProperties.class));
        byte[] header = {0, 0, 0, 12, 'f', 't', 'y', 'p', 'q', 't', ' ', ' '};
        var response = controller.analyzeVideo(new MockMultipartFile("file", "synthetic.mov", "video/quicktime", header));
        assertEquals(429, response.getStatusCode().value());
        assertEquals("30", response.getHeaders().getFirst("Retry-After"));
        assertFalse(response.getBody().toString().contains("verdict"));
        verify(service).failJob(eq("synthetic-job"), eq("SERVER_BUSY"), anyString());
    }

    @Test
    void negativeQueueCapacityIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> new AsyncConfig().analysisExecutor(-1));
    }

    @Test
    void dispatchFailureDoesNotLeaveAJobProcessingForever() {
        var service = mock(VideoAnalysisService.class);
        when(service.createJob()).thenReturn("synthetic-job");
        doThrow(new IllegalStateException("synthetic executor failure"))
                .when(service).processVideoAsync(eq("synthetic-job"), any());
        var controller = new AnalyzeController(service, new ObjectMapper(), mock(AppProperties.class));
        byte[] header = {0, 0, 0, 12, 'f', 't', 'y', 'p', 'q', 't', ' ', ' '};
        var response = controller.analyzeVideo(new MockMultipartFile("file", "synthetic.mov", "video/quicktime", header));
        assertEquals(500, response.getStatusCode().value());
        verify(service).failJob(eq("synthetic-job"), eq("UPLOAD_FAILED"), anyString());
    }
}
