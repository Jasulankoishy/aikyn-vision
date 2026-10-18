package com.datathon.backend;

import com.datathon.backend.config.AppProperties;
import com.datathon.backend.entity.JobEntity;
import com.datathon.backend.repository.JobRepository;
import com.datathon.backend.service.VideoAnalysisService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class CompletedAnalysisTests {
    @TempDir Path tempDir;
    private final ObjectMapper mapper = new ObjectMapper();

    private JsonNode process(String payload, int httpStatus) throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/analyze", exchange -> {
            exchange.getRequestBody().readAllBytes();
            byte[] body = payload.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(httpStatus, body.length);
            try (var output = exchange.getResponseBody()) { output.write(body); }
        });
        server.start();
        try {
            var repository = mock(JobRepository.class);
            var job = JobEntity.builder().jobId("synthetic-job").status("processing").createdAt(1L).build();
            when(repository.findById("synthetic-job")).thenReturn(Optional.of(job));
            var props = new AppProperties("synthetic-test-key", "real", "auto", "unused.py",
                    "http://127.0.0.1:" + server.getAddress().getPort(), 1, 24, List.of());
            var file = Files.write(tempDir.resolve("synthetic.mov"), new byte[]{1, 2, 3}).toFile();
            new VideoAnalysisService(repository, mapper, props).processVideoAsync("synthetic-job", file);
            assertFalse(file.exists(), "Uploads must be removed on success and failure");
            verify(repository).save(job);
            return mapper.readTree(job.getResultJson());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void completedEmptyAnalysisIsSuccessful() throws Exception {
        var result = process("{\"verdict\":\"no_violation\",\"violations\":[],\"analysis\":{\"complete\":true}}", 200);
        assertEquals("done", result.path("status").asText());
        assertEquals("no_violation", result.path("verdict").asText());
        assertTrue(result.path("violations").isEmpty());
    }

    @Test
    void preservesActualEventTimecode() throws Exception {
        var result = process("{\"verdict\":\"violation\",\"violations\":[{\"timecode_sec\":12.25,\"start_sec\":12.25,\"end_sec\":13.75}]}", 200);
        assertEquals("done", result.path("status").asText());
        assertEquals(12.25, result.path("violations").get(0).path("timecode_sec").asDouble());
        assertEquals(13.75, result.path("violations").get(0).path("end_sec").asDouble());
    }

    @Test
    void invalidPartialAndErrorResponsesNeverBecomeNoSignals() throws Exception {
        for (String body : List.of("{}", "{\"status\":\"failed\"}",
                "{\"verdict\":\"no_violation\",\"violations\":[],\"error\":{\"code\":\"failed\"}}",
                "{\"verdict\":\"violation\",\"violations\":[]}",
                "{\"verdict\":\"violation\",\"violations\":[{}]}",
                "{\"verdict\":\"no_violation\",\"violations\":[],\"analysis\":{\"complete\":false}}")) {
            var result = process(body, 200);
            assertEquals("failed", result.path("status").asText());
            assertFalse(result.has("verdict"));
            assertTrue(result.has("error"));
        }
    }

    @Test
    void serviceTimeoutReturnsFailureWithoutVerdict() throws Exception {
        var result = process("{\"detail\":\"time budget exceeded\"}", 504);
        assertEquals("failed", result.path("status").asText());
        assertEquals("TIMEOUT", result.path("error").path("code").asText());
        assertFalse(result.has("verdict"));
    }

    @Test
    void experimentalResultRequiresEveryWindowToComplete() throws Exception {
        for (String windows : List.of("", ",\"windows_done\":1,\"windows_total\":2",
                ",\"windows_done\":0,\"windows_total\":0", ",\"windows_done\":1.0,\"windows_total\":1.0")) {
            var result = process("{\"verdict\":\"no_violation\",\"violations\":[],\"analysis\":{\"experimental\":true,\"complete\":true,\"timeline_covered\":true"
                    + windows + "}}", 200);
            assertEquals("failed", result.path("status").asText());
            assertEquals("INCOMPLETE_ANALYSIS", result.path("error").path("code").asText());
            assertFalse(result.has("verdict"));
        }
        var complete = process("{\"verdict\":\"no_violation\",\"violations\":[],\"analysis\":{\"experimental\":true,\"complete\":true,\"timeline_covered\":true,\"windows_done\":2,\"windows_total\":2}}", 200);
        assertEquals("done", complete.path("status").asText());
    }
}
