package com.ford.fc.middleware.cirequest.discounting;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Functional tests for DiscountingCIConstants.
 */
@DisplayName("DiscountingCIConstants Functional Tests")
class DiscountingCIConstantsTest {

    @Test
    @DisplayName("TIMEOUT_ERRTXT should contain 'Pinnacle Middleware'")
    void testTimeoutErrorText() {
        assertNotNull(DiscountingCIConstants.TIMEOUT_ERRTXT);
        assertTrue(DiscountingCIConstants.TIMEOUT_ERRTXT.contains("Pinnacle Middleware"),
            "Timeout error text should reference Pinnacle Middleware");
        assertTrue(DiscountingCIConstants.TIMEOUT_ERRTXT.contains("Vincent"),
            "Timeout error text should reference Vincent");
    }

    @Test
    @DisplayName("TIMESTAMP key should be 'timestamp'")
    void testTimestamp() {
        assertEquals("timestamp", DiscountingCIConstants.TIMESTAMP);
    }

    @Test
    @DisplayName("VINCENT_PERFORMANCE key should be 'vincentRt'")
    void testVincentPerformance() {
        assertEquals("vincentRt", DiscountingCIConstants.VINCENT_PERFORMANCE);
    }

    @Test
    @DisplayName("JAVAMIDWARE_PERFORMANCE key should be 'javaMidWare'")
    void testJavaMidwarePerformance() {
        assertEquals("javaMidWare", DiscountingCIConstants.JAVAMIDWARE_PERFORMANCE);
    }

    @Test
    @DisplayName("TIMOUT_EX should be 'Read timed out'")
    void testTimeoutException() {
        assertEquals("Read timed out", DiscountingCIConstants.TIMOUT_EX);
    }

    @Test
    @DisplayName("Should be a utility class with private constructor")
    void testNotInstantiable() {
        var constructors = DiscountingCIConstants.class.getDeclaredConstructors();
        for (var c : constructors) {
            assertTrue(java.lang.reflect.Modifier.isPrivate(c.getModifiers()),
                "DiscountingCIConstants constructor should be private");
        }
    }
}
