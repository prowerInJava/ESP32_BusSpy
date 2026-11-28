#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_check.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs.h"
#include "nvs_flash.h"

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"

#include "lwip/inet.h"

#include "wifi_config_page.h"
#include "wifi_portal.h"

#define WIFI_AP_SSID "BusSpy-S3"
#define WIFI_AP_MAX_CONNECTIONS 1
#define WIFI_CREDENTIALS_NAMESPACE "busspy_wifi"
#define WIFI_SCAN_RESULT_LIMIT 20
#define WIFI_FORM_MAX_LENGTH 256
#define WIFI_PORTAL_CREDENTIALS_SET_BIT (1U << 3)

static const char *TAG = "wifi_portal";
static EventGroupHandle_t s_status_events;
static esp_netif_t *s_sta_netif;
static wifi_portal_led_set_fn s_led_set;
static wifi_portal_led_get_fn s_led_get;

static esp_err_t send_json_error(httpd_req_t *request, const char *status,
                                 const char *message)
{
    httpd_resp_set_status(request, status);
    httpd_resp_set_type(request, "application/json; charset=utf-8");
    char body[160];
    const int length = snprintf(body, sizeof(body),
                                "{\"ok\":0,\"msg\":\"%s\"}", message);
    if (length < 0 || (size_t)length >= sizeof(body)) {
        return ESP_FAIL;
    }
    return httpd_resp_send(request, body, length);
}

static size_t valid_utf8_length(const uint8_t *text, size_t remaining)
{
    const uint8_t first = text[0];
    if (first >= 0xC2 && first <= 0xDF && remaining >= 2 &&
        text[1] >= 0x80 && text[1] <= 0xBF) {
        return 2;
    }
    if (remaining >= 3 && text[1] >= 0x80 && text[1] <= 0xBF &&
        text[2] >= 0x80 && text[2] <= 0xBF) {
        if ((first == 0xE0 && text[1] >= 0xA0) ||
            (first >= 0xE1 && first <= 0xEC) ||
            (first == 0xED && text[1] <= 0x9F) ||
            (first >= 0xEE && first <= 0xEF)) {
            return 3;
        }
    }
    if (remaining >= 4 && text[2] >= 0x80 && text[2] <= 0xBF &&
        text[3] >= 0x80 && text[3] <= 0xBF) {
        if ((first == 0xF0 && text[1] >= 0x90 && text[1] <= 0xBF) ||
            (first >= 0xF1 && first <= 0xF3 &&
             text[1] >= 0x80 && text[1] <= 0xBF) ||
            (first == 0xF4 && text[1] >= 0x80 && text[1] <= 0x8F)) {
            return 4;
        }
    }
    return 0;
}

static esp_err_t send_json_escaped(httpd_req_t *request, const uint8_t *value,
                                   size_t value_length)
{
    char escaped[32 * 6 + 1];
    size_t output_length = 0;
    for (size_t i = 0; i < value_length; i++) {
        const uint8_t ch = value[i];
        if (ch == '"' || ch == '\\') {
            escaped[output_length++] = '\\';
            escaped[output_length++] = (char)ch;
        } else if (ch < 0x20) {
            const int written = snprintf(&escaped[output_length],
                                         sizeof(escaped) - output_length,
                                         "\\u%04x", ch);
            if (written != 6) {
                return ESP_FAIL;
            }
            output_length += (size_t)written;
        } else if (ch >= 0x80) {
            const size_t sequence_length =
                valid_utf8_length(&value[i], value_length - i);
            if (sequence_length != 0) {
                memcpy(&escaped[output_length], &value[i], sequence_length);
                output_length += sequence_length;
                i += sequence_length - 1;
            } else {
                const int written = snprintf(
                    &escaped[output_length], sizeof(escaped) - output_length,
                    "\\u%04x", ch);
                if (written != 6) {
                    return ESP_FAIL;
                }
                output_length += (size_t)written;
            }
        } else {
            escaped[output_length++] = (char)ch;
        }
    }
    if (output_length == 0) {
        return ESP_OK;
    }
    return httpd_resp_send_chunk(request, escaped, output_length);
}

static esp_err_t page_handler(httpd_req_t *request)
{
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    return httpd_resp_send(request, WIFI_CONFIG_PAGE, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t status_handler(httpd_req_t *request)
{
    const EventBits_t status = xEventGroupGetBits(s_status_events);
    const bool sta_connected =
        (status & WIFI_PORTAL_STA_CONNECTED_BIT) != 0;
    bool led_enabled = false;
    uint32_t led_step_ms = 1000;
    if (s_led_get != NULL) {
        s_led_get(&led_enabled, &led_step_ms);
    }
    wifi_ap_record_t connected_ap = {0};
    int rssi = 0;
    char sta_ip[16] = "-";
    if (sta_connected) {
        if (esp_wifi_sta_get_ap_info(&connected_ap) == ESP_OK) {
            rssi = connected_ap.rssi;
        }
        esp_netif_ip_info_t ip_info = {0};
        if (esp_netif_get_ip_info(s_sta_netif, &ip_info) == ESP_OK) {
            ip4addr_ntoa_r(&ip_info.ip, sta_ip, sizeof(sta_ip));
        }
    }

    char prefix[224];
    const int prefix_length = snprintf(
        prefix, sizeof(prefix),
        "{\"ok\":1,\"mode\":\"AP%s\",\"ip\":\"192.168.4.1\","
        "\"sta_connected\":%s,\"sta_ip\":\"%s\",\"rssi\":%d,"
        "\"rgb\":%s,\"color\":\"GREEN\",\"step\":",
        sta_connected ? "+STA" : "",
        sta_connected ? "true" : "false", sta_ip, rssi,
        led_enabled ? "true" : "false");
    if (prefix_length < 0 || (size_t)prefix_length >= sizeof(prefix)) {
        return ESP_FAIL;
    }

    const int step_length = snprintf(&prefix[prefix_length],
                                     sizeof(prefix) - (size_t)prefix_length,
                                     "%lu,\"ble\":%s,\"sta_ssid\":\"",
                                     (unsigned long)led_step_ms,
                                     (status & WIFI_PORTAL_BLE_CONNECTED_BIT)
                                         ? "true"
                                         : "false");
    if (step_length < 0 ||
        (size_t)step_length >= sizeof(prefix) - (size_t)prefix_length) {
        return ESP_FAIL;
    }

    httpd_resp_set_type(request, "application/json; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    esp_err_t err = httpd_resp_send_chunk(request, prefix,
                                          prefix_length + step_length);
    if (err != ESP_OK) {
        return err;
    }
    if (sta_connected) {
        err = send_json_escaped(request, connected_ap.ssid,
                                strnlen((const char *)connected_ap.ssid,
                                        sizeof(connected_ap.ssid)));
    }
    if (err != ESP_OK) {
        return err;
    }
    return httpd_resp_sendstr_chunk(request, "\"}");
}

static esp_err_t scan_handler(httpd_req_t *request)
{
    wifi_scan_config_t scan_config = {0};
    scan_config.scan_type = WIFI_SCAN_TYPE_ACTIVE;
    scan_config.scan_time.active.min = 100;
    scan_config.scan_time.active.max = 250;
    esp_err_t err = esp_wifi_scan_start(&scan_config, true);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Wi-Fi scan failed: %s", esp_err_to_name(err));
        return send_json_error(request, "503 Service Unavailable",
                               "Wi-Fi scan failed");
    }

    wifi_ap_record_t records[WIFI_SCAN_RESULT_LIMIT] = {0};
    uint16_t count = WIFI_SCAN_RESULT_LIMIT;
    err = esp_wifi_scan_get_ap_records(&count, records);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Could not read Wi-Fi scan results: %s",
                 esp_err_to_name(err));
        return send_json_error(request, "500 Internal Server Error",
                               "Could not read scan results");
    }

    httpd_resp_set_type(request, "application/json; charset=utf-8");
    err = httpd_resp_sendstr_chunk(request, "{\"ok\":1,\"list\":[");
    for (uint16_t i = 0; err == ESP_OK && i < count; i++) {
        char item[64];
        int length = snprintf(
            item, sizeof(item), "%s{\"s\":\"", i == 0 ? "" : ",");
        if (length < 0 || (size_t)length >= sizeof(item)) {
            return ESP_FAIL;
        }
        err = httpd_resp_send_chunk(request, item, length);
        if (err != ESP_OK) {
            return err;
        }
        const size_t ssid_length =
            strnlen((const char *)records[i].ssid, sizeof(records[i].ssid));
        err = send_json_escaped(request, records[i].ssid, ssid_length);
        if (err != ESP_OK) {
            return err;
        }
        length = snprintf(item, sizeof(item), "\",\"r\":%d,\"e\":%s}",
                          records[i].rssi,
                          records[i].authmode == WIFI_AUTH_OPEN
                              ? "false"
                              : "true");
        if (length < 0 || (size_t)length >= sizeof(item)) {
            return ESP_FAIL;
        }
        err = httpd_resp_send_chunk(request, item, length);
    }
    if (err != ESP_OK) {
        return err;
    }
    return httpd_resp_sendstr_chunk(request, "]}");
}

static int hex_value(char ch)
{
    if (ch >= '0' && ch <= '9') {
        return ch - '0';
    }
    if (ch >= 'a' && ch <= 'f') {
        return ch - 'a' + 10;
    }
    if (ch >= 'A' && ch <= 'F') {
        return ch - 'A' + 10;
    }
    return -1;
}

static bool decode_form_component(const char *source, size_t source_length,
                                  char *destination, size_t destination_size)
{
    size_t output_length = 0;
    for (size_t i = 0; i < source_length; i++) {
        unsigned char ch = (unsigned char)source[i];
        if (ch == '+') {
            ch = ' ';
        } else if (ch == '%') {
            if (i + 2 >= source_length) {
                return false;
            }
            const int high = hex_value(source[i + 1]);
            const int low = hex_value(source[i + 2]);
            if (high < 0 || low < 0) {
                return false;
            }
            ch = (unsigned char)((high << 4) | low);
            i += 2;
        }
        if (ch == '\0' || output_length + 1 >= destination_size) {
            return false;
        }
        destination[output_length++] = (char)ch;
    }
    destination[output_length] = '\0';
    return true;
}

static bool form_value(const char *body, const char *key, char *destination,
                       size_t destination_size)
{
    const size_t key_length = strlen(key);
    const char *field = body;
    while (*field != '\0') {
        const char *equals = strchr(field, '=');
        if (equals == NULL) {
            return false;
        }
        const char *end = strchr(equals + 1, '&');
        if (end == NULL) {
            end = body + strlen(body);
        }
        if ((size_t)(equals - field) == key_length &&
            memcmp(field, key, key_length) == 0) {
            return decode_form_component(equals + 1,
                                         (size_t)(end - equals - 1),
                                         destination, destination_size);
        }
        field = (*end == '&') ? end + 1 : end;
    }
    return false;
}

static esp_err_t receive_form(httpd_req_t *request, char *body,
                              size_t body_size)
{
    if (request->content_len == 0 ||
        request->content_len >= body_size ||
        request->content_len > WIFI_FORM_MAX_LENGTH) {
        return ESP_ERR_INVALID_SIZE;
    }

    size_t received = 0;
    while (received < request->content_len) {
        const int result = httpd_req_recv(
            request, &body[received], request->content_len - received);
        if (result <= 0) {
            return ESP_FAIL;
        }
        received += (size_t)result;
    }
    body[received] = '\0';
    return ESP_OK;
}

static esp_err_t save_wifi_credentials(const char *ssid, const char *password)
{
    nvs_handle_t nvs;
    ESP_RETURN_ON_ERROR(nvs_open(WIFI_CREDENTIALS_NAMESPACE, NVS_READWRITE,
                                 &nvs),
                        TAG, "Could not open Wi-Fi settings");
    esp_err_t err = nvs_set_str(nvs, "ssid", ssid);
    if (err == ESP_OK) {
        err = nvs_set_str(nvs, "pass", password);
    }
    if (err == ESP_OK) {
        err = nvs_commit(nvs);
    }
    nvs_close(nvs);
    return err;
}

static esp_err_t load_wifi_credentials(char *ssid, size_t ssid_size,
                                       char *password, size_t password_size,
                                       bool *found)
{
    *found = false;
    nvs_handle_t nvs;
    esp_err_t err = nvs_open(WIFI_CREDENTIALS_NAMESPACE, NVS_READONLY, &nvs);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        return ESP_OK;
    }
    ESP_RETURN_ON_ERROR(err, TAG, "Could not open saved Wi-Fi settings");

    size_t length = ssid_size;
    err = nvs_get_str(nvs, "ssid", ssid, &length);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        nvs_close(nvs);
        return ESP_OK;
    }
    if (err != ESP_OK) {
        nvs_close(nvs);
        return err;
    }

    length = password_size;
    err = nvs_get_str(nvs, "pass", password, &length);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        password[0] = '\0';
    } else if (err != ESP_OK) {
        nvs_close(nvs);
        return err;
    }
    nvs_close(nvs);

    if (ssid[0] == '\0' || strlen(ssid) > 32 || strlen(password) > 63) {
        return ESP_ERR_INVALID_SIZE;
    }
    *found = true;
    return ESP_OK;
}

static esp_err_t apply_wifi_credentials(const char *ssid, const char *password)
{
    wifi_config_t station_config = {0};
    memcpy(station_config.sta.ssid, ssid, strlen(ssid));
    memcpy(station_config.sta.password, password, strlen(password));
    station_config.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
    station_config.sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;

    xEventGroupClearBits(s_status_events, WIFI_PORTAL_CREDENTIALS_SET_BIT);
    (void)esp_wifi_disconnect();
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &station_config), TAG,
                        "Could not configure Wi-Fi station");
    xEventGroupSetBits(s_status_events, WIFI_PORTAL_CREDENTIALS_SET_BIT);
    return esp_wifi_connect();
}

static esp_err_t wifi_save_handler(httpd_req_t *request)
{
    char body[WIFI_FORM_MAX_LENGTH + 1];
    char ssid[33];
    char password[64];
    esp_err_t err = receive_form(request, body, sizeof(body));
    if (err != ESP_OK) {
        return send_json_error(request, "400 Bad Request",
                               "Invalid request body");
    }
    if (!form_value(body, "ssid", ssid, sizeof(ssid)) ||
        !form_value(body, "pass", password, sizeof(password)) ||
        ssid[0] == '\0' || strlen(ssid) > 32 || strlen(password) > 63) {
        return send_json_error(request, "400 Bad Request",
                               "SSID or password is invalid");
    }

    err = save_wifi_credentials(ssid, password);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Could not save Wi-Fi credentials: %s",
                 esp_err_to_name(err));
        return send_json_error(request, "500 Internal Server Error",
                               "Could not save Wi-Fi settings");
    }
    err = apply_wifi_credentials(ssid, password);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Could not start Wi-Fi connection: %s",
                 esp_err_to_name(err));
        return send_json_error(request, "500 Internal Server Error",
                               "Could not start Wi-Fi connection");
    }
    httpd_resp_set_type(request, "application/json; charset=utf-8");
    return httpd_resp_sendstr(request,
                              "{\"ok\":1,\"msg\":\"已保存，正在连接路由器\"}");
}

static esp_err_t led_handler(httpd_req_t *request)
{
    char body[64];
    char enabled_text[8];
    char step_text[8];
    esp_err_t err = receive_form(request, body, sizeof(body));
    if (err != ESP_OK ||
        !form_value(body, "on", enabled_text, sizeof(enabled_text)) ||
        !form_value(body, "step", step_text, sizeof(step_text)) ||
        (strcmp(enabled_text, "0") != 0 && strcmp(enabled_text, "1") != 0)) {
        return send_json_error(request, "400 Bad Request",
                               "Invalid LED settings");
    }

    char *end = NULL;
    const unsigned long step_ms = strtoul(step_text, &end, 10);
    if (end == step_text || *end != '\0' || step_ms < 100 || step_ms > 10000) {
        return send_json_error(request, "400 Bad Request",
                               "LED interval must be 100-10000 ms");
    }
    if (s_led_set != NULL) {
        s_led_set(strcmp(enabled_text, "1") == 0, (uint32_t)step_ms);
    }
    httpd_resp_set_type(request, "application/json; charset=utf-8");
    return httpd_resp_sendstr(request, "{\"ok\":1,\"msg\":\"已应用\"}");
}

static esp_err_t reset_handler(httpd_req_t *request)
{
    httpd_resp_set_type(request, "application/json; charset=utf-8");
    const esp_err_t err =
        httpd_resp_sendstr(request, "{\"ok\":1,\"msg\":\"设备正在重启\"}");
    if (err == ESP_OK) {
        vTaskDelay(pdMS_TO_TICKS(150));
        esp_restart();
    }
    return err;
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                              int32_t event_id, void *event_data)
{
    (void)arg;
    (void)event_data;
    if (event_base != WIFI_EVENT) {
        return;
    }
    if (event_id == WIFI_EVENT_AP_STACONNECTED) {
        xEventGroupSetBits(s_status_events, WIFI_PORTAL_AP_CLIENT_BIT);
        ESP_LOGI(TAG, "Setup page client connected");
    } else if (event_id == WIFI_EVENT_AP_STADISCONNECTED) {
        xEventGroupClearBits(s_status_events, WIFI_PORTAL_AP_CLIENT_BIT);
        ESP_LOGI(TAG, "Setup page client disconnected");
    } else if (event_id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_status_events, WIFI_PORTAL_STA_CONNECTED_BIT);
        if ((xEventGroupGetBits(s_status_events) &
             WIFI_PORTAL_CREDENTIALS_SET_BIT) != 0) {
            const esp_err_t err = esp_wifi_connect();
            if (err != ESP_OK) {
                ESP_LOGW(TAG, "Wi-Fi reconnect failed: %s",
                         esp_err_to_name(err));
            }
        }
    }
}

static void ip_event_handler(void *arg, esp_event_base_t event_base,
                             int32_t event_id, void *event_data)
{
    (void)arg;
    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        (void)event_data;
        xEventGroupSetBits(s_status_events, WIFI_PORTAL_STA_CONNECTED_BIT);
        ESP_LOGI(TAG, "Connected to router; station IP acquired");
        ESP_LOGI(TAG, "Use http://192.168.4.1/ for Wi-Fi setup");
    }
}

static esp_err_t start_http_server(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;
    config.max_uri_handlers = 8;
    config.stack_size = 8192;
    httpd_handle_t server = NULL;
    ESP_RETURN_ON_ERROR(httpd_start(&server, &config), TAG,
                        "Could not start setup web server");

    const httpd_uri_t handlers[] = {
        {.uri = "/", .method = HTTP_GET, .handler = page_handler},
        {.uri = "/api/status", .method = HTTP_GET, .handler = status_handler},
        {.uri = "/api/scan", .method = HTTP_GET, .handler = scan_handler},
        {.uri = "/api/led", .method = HTTP_POST, .handler = led_handler},
        {.uri = "/api/wifi", .method = HTTP_POST, .handler = wifi_save_handler},
        {.uri = "/api/reset", .method = HTTP_POST, .handler = reset_handler},
    };
    for (size_t i = 0; i < sizeof(handlers) / sizeof(handlers[0]); i++) {
        const esp_err_t err = httpd_register_uri_handler(server, &handlers[i]);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "Could not register setup page route: %s",
                     esp_err_to_name(err));
            httpd_stop(server);
            return err;
        }
    }
    ESP_LOGI(TAG, "Wi-Fi setup page: http://192.168.4.1/");
    return ESP_OK;
}

esp_err_t wifi_portal_start(EventGroupHandle_t status_events,
                            wifi_portal_led_set_fn led_set,
                            wifi_portal_led_get_fn led_get)
{
    const size_t ap_password_length = strlen(CONFIG_WIFI_AP_PASSWORD);
    if (ap_password_length < 8 || ap_password_length > 63) {
        ESP_LOGE(TAG, "Set a WPA2 setup hotspot password (8-63 chars) in "
                      "menuconfig before starting Wi-Fi");
        return ESP_ERR_INVALID_ARG;
    }
    s_status_events = status_events;
    s_led_set = led_set;
    s_led_get = led_get;

    ESP_RETURN_ON_ERROR(nvs_flash_init(), TAG,
                        "NVS init failed; refusing to erase stored settings");
    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "Network interface init failed");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), TAG,
                        "Default event loop init failed");
    esp_netif_create_default_wifi_ap();
    s_sta_netif = esp_netif_create_default_wifi_sta();

    const wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&init_config), TAG, "Wi-Fi init failed");
    ESP_RETURN_ON_ERROR(
        esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                   wifi_event_handler, NULL),
        TAG, "Wi-Fi event registration failed");
    ESP_RETURN_ON_ERROR(
        esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                   ip_event_handler, NULL),
        TAG, "IP event registration failed");

    wifi_config_t ap_config = {
        .ap = {
            .ssid = WIFI_AP_SSID,
            .ssid_len = sizeof(WIFI_AP_SSID) - 1,
            .channel = 1,
            .password = CONFIG_WIFI_AP_PASSWORD,
            .max_connection = WIFI_AP_MAX_CONNECTIONS,
            .authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_APSTA), TAG,
                        "Could not set AP+station mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_AP, &ap_config), TAG,
                        "Could not configure setup hotspot");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "Could not start Wi-Fi");
    ESP_RETURN_ON_ERROR(esp_wifi_set_ps(WIFI_PS_MIN_MODEM), TAG,
                        "Could not enable Wi-Fi/BLE coexistence power save");
    ESP_RETURN_ON_ERROR(start_http_server(), TAG,
                        "Could not start setup page");

    char ssid[33] = {0};
    char password[64] = {0};
    bool found_credentials = false;
    ESP_RETURN_ON_ERROR(load_wifi_credentials(
                            ssid, sizeof(ssid), password, sizeof(password),
                            &found_credentials),
                        TAG, "Could not load saved Wi-Fi settings");
    if (found_credentials) {
        ESP_LOGI(TAG, "Saved router credentials found; connecting");
        ESP_RETURN_ON_ERROR(apply_wifi_credentials(ssid, password), TAG,
                            "Could not start saved Wi-Fi connection");
    }

    ESP_LOGI(TAG, "Secured WPA2 hotspot '%s' ready", WIFI_AP_SSID);
    return ESP_OK;
}
