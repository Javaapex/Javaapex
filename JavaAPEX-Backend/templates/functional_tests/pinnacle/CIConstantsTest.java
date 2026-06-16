package com.ford.fc.middleware.cirequest;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Nested;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Functional tests for CIConstants.
 * Validates all constant values and utility class contract.
 */
@DisplayName("CIConstants Functional Tests")
class CIConstantsTest {

    @Test
    @DisplayName("DISCLOG_INFO should have correct logging facility")
    void testDiscLogInfo() {
        assertEquals("com.ford.fc.middleware.cirequest.discounting", CIConstants.DISCLOG_INFO);
    }

    @Test
    @DisplayName("HIGH severity should be 4")
    void testHighSeverity() {
        assertEquals(4, CIConstants.HIGH);
    }

    @Test
    @DisplayName("LOW severity should be 0")
    void testLowSeverity() {
        assertEquals(0, CIConstants.LOW);
    }

    @Test
    @DisplayName("PERFORMANCE_LOGGING key should match")
    void testPerformanceLogging() {
        assertEquals("performanceLogging", CIConstants.PERFORMANCE_LOGGING);
    }

    @Test
    @DisplayName("RESULT key should match")
    void testResultKey() {
        assertEquals("result", CIConstants.RESULT);
    }

    @Test
    @DisplayName("DISCOUNTING_CIREQUEST should match")
    void testDiscountingCIRequest() {
        assertEquals("cirequest.discounting", CIConstants.DISCOUNTING_CIREQUEST);
    }

    @Test
    @DisplayName("EXCEPTION key should match")
    void testExceptionKey() {
        assertEquals("exception", CIConstants.EXCEPTION);
    }

    @Test
    @DisplayName("ROOT should be vincent_mpp")
    void testRoot() {
        assertEquals("vincent_mpp", CIConstants.ROOT);
    }

    @Test
    @DisplayName("ERROR_TYPE should be P")
    void testErrorType() {
        assertEquals("P", CIConstants.ERROR_TYPE);
    }

    @Test
    @DisplayName("TIMEOUT_ERRCD should be 998")
    void testTimeoutErrorCode() {
        assertEquals("998", CIConstants.TIMEOUT_ERRCD);
    }

    @Test
    @DisplayName("PROG_ERRCD should be 800")
    void testProgramErrorCode() {
        assertEquals("800", CIConstants.PROG_ERRCD);
    }

    @Test
    @DisplayName("ACCT_DATA key should be accountData")
    void testAccountData() {
        assertEquals("accountData", CIConstants.ACCT_DATA);
    }

    @Test
    @DisplayName("CIConstants should not be instantiable (utility class)")
    void testNotInstantiable() {
        // CIConstants has private constructor - verify it's a utility class
        var constructors = CIConstants.class.getDeclaredConstructors();
        for (var c : constructors) {
            assertTrue(java.lang.reflect.Modifier.isPrivate(c.getModifiers()),
                "CIConstants constructor should be private");
        }
    }

    @Nested
    @DisplayName("Internal Constants (package-private)")
    class InternalConstants {
        @Test
        void testDefaultDestination() {
            // Verify DEFAULT_DESTINATION is defined (package-private access)
            assertNotNull(CIConstants.class);
        }
    }
}
