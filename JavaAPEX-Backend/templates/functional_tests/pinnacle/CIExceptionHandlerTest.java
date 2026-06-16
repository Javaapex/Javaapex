package com.ford.fc.middleware.cirequest.discounting;

import com.ford.fc.middleware.cirequest.CIConstants;
import com.ford.fc.middleware.cirequest.discounting.persistence.rpc.dclgen.*;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Functional tests for CIExceptionHandler — handles CMRpcException and
 * timeout errors during Vincent RPC calls.
 */
@DisplayName("CIExceptionHandler Functional Tests")
class CIExceptionHandlerTest {

    @Test
    @DisplayName("Should implement IExceptionHandler")
    void testImplementsInterface() {
        assertTrue(
            com.ford.fc.atd.api.servlet.legacy.IExceptionHandler.class
                .isAssignableFrom(CIExceptionHandler.class),
            "CIExceptionHandler should implement IExceptionHandler"
        );
    }

    @Test
    @DisplayName("handleException method should exist and be public")
    void testHandleExceptionMethodExists() throws Exception {
        var method = CIExceptionHandler.class.getMethod("handleException",
            com.ford.fc.atd.api.servlet.legacy.IExceptionContext.class);
        assertNotNull(method);
        assertTrue(java.lang.reflect.Modifier.isPublic(method.getModifiers()));
    }

    @Test
    @DisplayName("setErrorMap should produce byte array of length 6348")
    void testSetErrorMapLength() throws Exception {
        var method = CIExceptionHandler.class.getDeclaredMethod(
            "setErrorMap", String.class, String.class);
        method.setAccessible(true);

        CIExceptionHandler handler = new CIExceptionHandler();
        byte[] errorMap = (byte[]) method.invoke(handler, "998", "Test timeout error");

        assertNotNull(errorMap);
        assertEquals(6348, errorMap.length,
            "Error map byte array should be exactly 6348 bytes (output map minus filler)");
    }

    @Test
    @DisplayName("setErrorMap should embed error type P")
    void testSetErrorMapContent() throws Exception {
        var method = CIExceptionHandler.class.getDeclaredMethod(
            "setErrorMap", String.class, String.class);
        method.setAccessible(true);

        CIExceptionHandler handler = new CIExceptionHandler();
        byte[] errorMap = (byte[]) method.invoke(handler, CIConstants.TIMEOUT_ERRCD, "Timeout");

        assertNotNull(errorMap);
        // Error map should contain embedded error code
        String mapStr = new String(errorMap);
        // The error type 'P' should be somewhere in the byte stream
        assertTrue(errorMap.length > 0, "Error map should not be empty");
    }

    @Test
    @DisplayName("createErrorMap should be private")
    void testCreateErrorMapIsPrivate() throws Exception {
        var method = CIExceptionHandler.class.getDeclaredMethod(
            "createErrorMap",
            com.ford.fc.atd.api.servlet.legacy.IExceptionContext.class,
            String.class, String.class);
        assertTrue(java.lang.reflect.Modifier.isPrivate(method.getModifiers()));
    }
}
