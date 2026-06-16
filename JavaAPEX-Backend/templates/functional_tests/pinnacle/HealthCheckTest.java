package com.ford.fc.middleware.servlet;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.PrintWriter;
import java.io.StringWriter;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * Functional tests for HealthCheck servlet — the /health endpoint 
 * used by PCF/Kubernetes probes.
 */
@DisplayName("HealthCheck Servlet Functional Tests")
class HealthCheckTest {

    private HealthCheck healthCheck;
    private HttpServletRequest request;
    private HttpServletResponse response;
    private StringWriter responseBody;

    @BeforeEach
    void setUp() throws Exception {
        healthCheck = new HealthCheck();
        request = mock(HttpServletRequest.class);
        response = mock(HttpServletResponse.class);
        responseBody = new StringWriter();
        when(response.getWriter()).thenReturn(new PrintWriter(responseBody));
    }

    @Test
    @DisplayName("GET /health should return JSON with status pass")
    void testHealthCheckReturnsPass() throws Exception {
        healthCheck.doGet(request, response);

        verify(response).setContentType("application/json");
        String body = responseBody.toString().trim();
        assertTrue(body.contains("\"status\""), "Response should contain status key");
        assertTrue(body.contains("\"pass\""), "Status should be 'pass'");
    }

    @Test
    @DisplayName("Response should be valid JSON")
    void testResponseIsValidJson() throws Exception {
        healthCheck.doGet(request, response);

        String body = responseBody.toString().trim();
        assertTrue(body.startsWith("{") && body.endsWith("}"),
            "Response should be a JSON object");
    }

    @Test
    @DisplayName("Content-Type should be application/json")
    void testContentType() throws Exception {
        healthCheck.doGet(request, response);
        verify(response).setContentType("application/json");
    }

    @Test
    @DisplayName("HealthCheck should extend HttpServlet")
    void testInheritance() {
        assertTrue(
            javax.servlet.http.HttpServlet.class.isAssignableFrom(HealthCheck.class),
            "HealthCheck should extend HttpServlet"
        );
    }

    @Test
    @DisplayName("serialVersionUID should be set")
    void testSerialVersionUID() throws Exception {
        var field = HealthCheck.class.getDeclaredField("serialVersionUID");
        field.setAccessible(true);
        long uid = field.getLong(null);
        assertEquals(-2171623067668447946L, uid);
    }
}
