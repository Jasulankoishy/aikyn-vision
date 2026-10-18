package com.datathon.backend;

import com.datathon.backend.config.AppProperties;
import com.datathon.backend.controller.LocalSessionController;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class LocalSessionTests {
    private final AppProperties props = mock(AppProperties.class);

    private MockHttpServletRequest localRequest() {
        var request = new MockHttpServletRequest("GET", "/local-session");
        request.setRemoteAddr("127.0.0.1");
        request.setLocalAddr("127.0.0.1");
        request.setLocalPort(8080);
        request.addHeader("Host", "127.0.0.1:8080");
        request.addHeader("Sec-Fetch-Site", "same-origin");
        request.addHeader("X-Local-Bootstrap", "1");
        return request;
    }

    @Test
    void localBrowserReceivesAnUncachedMemoryOnlyConnection() {
        when(props.apiKey()).thenReturn("synthetic-test-key");
        when(props.mode()).thenReturn("real");
        var response = new LocalSessionController(props, true).localSession(localRequest());
        assertEquals(200, response.getStatusCode().value());
        assertEquals("no-store", response.getHeaders().getCacheControl());
        assertEquals("synthetic-test-key", ((Map<?, ?>) response.getBody()).get("api_key"));
    }

    @Test
    void bootstrapIsDisabledByDefaultForOtherDeployments() {
        assertEquals(403, new LocalSessionController(props, false).localSession(localRequest()).getStatusCode().value());
        verifyNoInteractions(props);
    }

    @Test
    void rejectsRemoteClientsCrossOriginRequestsAndHostRebinding() {
        var controller = new LocalSessionController(props, true);
        var remote = localRequest(); remote.setRemoteAddr("192.168.1.10");
        var network = localRequest(); network.setLocalAddr("192.168.1.2");
        var crossOrigin = localRequest(); crossOrigin.removeHeader("Sec-Fetch-Site"); crossOrigin.addHeader("Sec-Fetch-Site", "cross-site");
        var sameSite = localRequest(); sameSite.removeHeader("Sec-Fetch-Site"); sameSite.addHeader("Sec-Fetch-Site", "same-site");
        var missingMetadata = localRequest(); missingMetadata.removeHeader("Sec-Fetch-Site");
        var missingCustomHeader = localRequest(); missingCustomHeader.removeHeader("X-Local-Bootstrap");
        var origin = localRequest(); origin.addHeader("Origin", "https://example.invalid");
        var rebound = localRequest(); rebound.removeHeader("Host"); rebound.addHeader("Host", "example.invalid:8080");
        var wrongPort = localRequest(); wrongPort.removeHeader("Host"); wrongPort.addHeader("Host", "localhost:4321");
        var userinfo = localRequest(); userinfo.removeHeader("Host"); userinfo.addHeader("Host", "attacker@localhost:8080");
        for (var request : new MockHttpServletRequest[]{remote, network, crossOrigin, sameSite, missingMetadata,
                missingCustomHeader, origin, rebound, wrongPort, userinfo}) {
            assertEquals(403, controller.localSession(request).getStatusCode().value());
        }
        verifyNoInteractions(props);
    }
}
