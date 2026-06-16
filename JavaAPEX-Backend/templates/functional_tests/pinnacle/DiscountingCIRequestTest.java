package com.ford.fc.middleware.cirequest.discounting;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.time.Instant;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Functional tests for DiscountingCIRequest — the main request handler 
 * for the Pinnacle middleware CI discounting flow.
 */
@DisplayName("DiscountingCIRequest Functional Tests")
class DiscountingCIRequestTest {

    @Test
    @DisplayName("Class should extend AbstractRequest")
    void testInheritance() {
        assertTrue(
            com.ford.fc.atd.servlet.legacy.AbstractRequest.class.isAssignableFrom(DiscountingCIRequest.class),
            "DiscountingCIRequest should extend AbstractRequest"
        );
    }

    @Test
    @DisplayName("serialVersionUID should be 47956023")
    void testSerialVersionUID() throws Exception {
        var field = DiscountingCIRequest.class.getDeclaredField("serialVersionUID");
        field.setAccessible(true);
        assertEquals(47956023L, field.getLong(null));
    }

    @Test
    @DisplayName("isLogonRequired should return false")
    void testIsLogonRequired() {
        DiscountingCIRequest request = new DiscountingCIRequest();
        assertFalse(request.isLogonRequired(),
            "Pinnacle middleware does not require logon");
    }

    @Test
    @DisplayName("getNextPage should return empty string")
    void testGetNextPage() {
        DiscountingCIRequest request = new DiscountingCIRequest();
        assertEquals("", request.getNextPage(),
            "Next page should be empty — this is a REST-style middleware");
    }

    @Test
    @DisplayName("createResponse should return DiscountingCIResponse instance")
    void testCreateResponse() {
        DiscountingCIRequest request = new DiscountingCIRequest();
        var response = request.createResponse();
        assertNotNull(response);
        assertInstanceOf(DiscountingCIResponse.class, response,
            "createResponse should return DiscountingCIResponse");
    }

    @Test
    @DisplayName("currentdatetime should return formatted timestamp")
    void testCurrentDatetime() {
        DiscountingCIRequest request = new DiscountingCIRequest();
        String datetime = request.currentdatetime();
        assertNotNull(datetime);
        // Format: yyyy-MM-dd HH:mm:ss.SSS
        assertTrue(datetime.matches("\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}\\.\\d{3}"),
            "Datetime should match pattern yyyy-MM-dd HH:mm:ss.SSS but was: " + datetime);
    }

    @Test
    @DisplayName("requestCI should be private method")
    void testRequestCIIsPrivate() throws Exception {
        Method method = DiscountingCIRequest.class.getDeclaredMethod("requestCI");
        assertTrue(Modifier.isPrivate(method.getModifiers()),
            "requestCI should be a private method");
    }

    @Test
    @DisplayName("getContextInfo should be private method")
    void testGetContextInfoIsPrivate() throws Exception {
        Method method = DiscountingCIRequest.class.getDeclaredMethod("getContextInfo");
        assertTrue(Modifier.isPrivate(method.getModifiers()),
            "getContextInfo should be a private method");
    }

    @Test
    @DisplayName("postValidate should be protected method")
    void testPostValidateIsProtected() throws Exception {
        Method method = DiscountingCIRequest.class.getDeclaredMethod("postValidate");
        assertTrue(Modifier.isProtected(method.getModifiers()),
            "postValidate should be a protected method");
    }
}
