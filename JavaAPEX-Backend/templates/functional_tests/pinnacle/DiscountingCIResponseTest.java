package com.ford.fc.middleware.cirequest.discounting;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Functional tests for DiscountingCIResponse — handles sending the 
 * byte-stream response back to MD&R.
 */
@DisplayName("DiscountingCIResponse Functional Tests")
class DiscountingCIResponseTest {

    @Test
    @DisplayName("Class should extend AbstractResponse")
    void testInheritance() {
        assertTrue(
            com.ford.fc.atd.core.servlet.legacy.AbstractResponse.class.isAssignableFrom(
                DiscountingCIResponse.class),
            "DiscountingCIResponse should extend AbstractResponse"
        );
    }

    @Test
    @DisplayName("serialVersionUID should be 1L")
    void testSerialVersionUID() throws Exception {
        var field = DiscountingCIResponse.class.getDeclaredField("serialVersionUID");
        field.setAccessible(true);
        assertEquals(1L, field.getLong(null));
    }

    @Test
    @DisplayName("Default constructor should create valid instance")
    void testDefaultConstructor() {
        DiscountingCIResponse response = new DiscountingCIResponse();
        assertNotNull(response);
    }

    @Test
    @DisplayName("execute(String, INVList) should throw ServletException (deprecated path)")
    void testExecuteWithINVListThrows() {
        DiscountingCIResponse response = new DiscountingCIResponse();
        assertThrows(
            com.ford.fc.atd.api.servlet.ServletException.class,
            () -> response.execute("", null),
            "Calling execute(String, INVList) should throw — only Map version is valid"
        );
    }
}
