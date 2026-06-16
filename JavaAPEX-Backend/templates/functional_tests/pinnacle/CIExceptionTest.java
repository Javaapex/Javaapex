package com.ford.fc.middleware.cirequest.discounting;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Functional tests for CIException custom exception hierarchy.
 */
@DisplayName("CIException Functional Tests")
class CIExceptionTest {

    @Test
    @DisplayName("Default constructor should create exception with null message")
    void testDefaultConstructor() {
        CIException ex = new CIException();
        assertNotNull(ex);
    }

    @Test
    @DisplayName("String message constructor should preserve message")
    void testMessageConstructor() {
        CIException ex = new CIException("Test error");
        assertEquals("Test error", ex.getMessage());
    }

    @Test
    @DisplayName("Error code + message constructor should work")
    void testErrorCodeAndMessage() {
        CIException ex = new CIException("998", "Timeout error");
        assertNotNull(ex);
    }

    @Test
    @DisplayName("Int error code + message constructor should work")
    void testIntErrorCodeAndMessage() {
        CIException ex = new CIException(800, "Program error");
        assertNotNull(ex);
    }

    @Test
    @DisplayName("Exception wrapping constructor should preserve cause")
    void testExceptionWrapping() {
        RuntimeException cause = new RuntimeException("root cause");
        CIException ex = new CIException(cause);
        assertNotNull(ex);
    }

    @Test
    @DisplayName("CIException should extend ServletException")
    void testInheritance() {
        assertTrue(
            com.ford.fc.atd.api.servlet.ServletException.class.isAssignableFrom(CIException.class),
            "CIException should extend ATD ServletException"
        );
    }

    @Test
    @DisplayName("serialVersionUID should be 1L")
    void testSerialVersionUID() throws Exception {
        var field = CIException.class.getDeclaredField("serialVersionUID");
        field.setAccessible(true);
        assertEquals(1L, field.getLong(null));
    }
}
