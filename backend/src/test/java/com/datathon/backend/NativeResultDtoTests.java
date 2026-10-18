package com.datathon.backend;

import com.datathon.backend.dto.JobStatusResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class NativeResultDtoTests {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void nativeIntervalsAndReviewStatusSurviveTheServiceAndDatabaseRoundTrip() throws Exception {
        String workerJson = """
                {
                  "verdict": "violation",
                  "violations": [{
                    "type": "Synthetic possible event",
                    "timecode_sec": 12.25,
                    "start_sec": 12.25,
                    "end_sec": 13.75,
                    "category_id": "c02",
                    "localization": "dense_sample_support",
                    "status": "possible_sign_requires_review",
                    "description": "Synthetic contract fixture; not a bank observation.",
                    "evidence_frames": []
                  }],
                  "analysis": {
                    "experimental": true,
                    "new_training": false,
                    "findings_status": "requires_review",
                    "complete": true,
                    "timeline_covered": true,
                    "windows_done": 3,
                    "windows_total": 3,
                    "refinements": [{"start_sec": 12.25, "end_sec": 13.75}]
                  }
                }
                """;
        var result = mapper.readValue(workerJson, JobStatusResponse.class);
        result.setJobId("synthetic-job");
        result.setStatus("done");
        result.setMode("real");
        // The service serializes to SQLite and the controller deserializes that stored result.
        var reloaded = mapper.readValue(mapper.writeValueAsString(result), JobStatusResponse.class);
        var json = mapper.readTree(mapper.writeValueAsString(reloaded));
        var event = json.path("violations").get(0);
        assertEquals(12.25, event.path("start_sec").asDouble());
        assertEquals(13.75, event.path("end_sec").asDouble());
        assertEquals(12.25, event.path("timecode_sec").asDouble());
        assertEquals("c02", event.path("category_id").asText());
        assertEquals("dense_sample_support", event.path("localization").asText());
        assertEquals("possible_sign_requires_review", event.path("status").asText());
        assertEquals("done", json.path("status").asText());
        assertTrue(json.path("analysis").path("experimental").asBoolean());
        assertFalse(json.path("analysis").path("new_training").asBoolean());
        assertEquals("requires_review", json.path("analysis").path("findings_status").asText());
        assertEquals(13.75, json.path("analysis").path("refinements").get(0).path("end_sec").asDouble());
        assertFalse(event.has("startSec"));
        assertFalse(event.has("categoryId"));
    }

    @Test
    void oldSingleTimestampEventsDoNotAcquireInventedBoundaries() throws Exception {
        var oldResult = mapper.readValue("""
                {"verdict":"violation","violations":[{"type":"legacy","timecode_sec":2.5,
                "description":"Synthetic legacy event","evidence_frames":[]}]}
                """, JobStatusResponse.class);
        var event = mapper.readTree(mapper.writeValueAsString(oldResult)).path("violations").get(0);
        assertEquals(2.5, event.path("timecode_sec").asDouble());
        for (String optional : new String[]{"start_sec", "end_sec", "category_id", "localization", "status"}) {
            assertFalse(event.has(optional), "Legacy events must not invent " + optional);
        }
    }
}
