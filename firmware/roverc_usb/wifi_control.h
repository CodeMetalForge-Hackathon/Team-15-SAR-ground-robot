#pragma once
#include <WiFi.h>
#include <ArduinoJson.h>
#include <Preferences.h>

// Router-free AP is always available. Saved station credentials are private to NVS.
class RoverNetwork {
 public:
  WiFiServer server{5000};
  WiFiClient client;
  String ssid;
  String password;
  String stationSSID;
  bool apReady = false;
  bool serverReady = false;
  bool joining = false;
  uint32_t joinStarted = 0;

  void begin() {
    Preferences settings;
    settings.begin("rover-wifi", false);
    password = settings.getString("ap-pass", "");
    if (password.length() != 16) {
      char generated[17];
      snprintf(generated, sizeof(generated), "%08lx%08lx",
               (unsigned long)esp_random(), (unsigned long)esp_random());
      password = generated;
      settings.putString("ap-pass", password);
    }
    stationSSID = settings.getString("sta-ssid", "");
    String stationPass = settings.getString("sta-pass", "");
    settings.end();
    char name[24];
    snprintf(name, sizeof(name), "RoverC-%04X", (unsigned)(ESP.getEfuseMac() & 0xffff));
    ssid = name;
    WiFi.mode(WIFI_AP_STA);
    WiFi.setAutoReconnect(true);
    apReady = WiFi.softAP(ssid.c_str(), password.c_str(), 6, false, 1);
    server.begin();
    server.setNoDelay(true);
    serverReady = true;
    if (stationSSID.length()) startStation(stationPass);
  }

  void startStation(const String& pass) {
    WiFi.begin(stationSSID.c_str(), pass.c_str());
    joinStarted = millis();
    joining = true;
  }

  void tick() {
    if (joining && WiFi.status() == WL_CONNECTED) joining = false;
    if (joining && uint32_t(millis() - joinStarted) > 20000) {
      WiFi.disconnect(false, false);
      joining = false;  // AP remains usable even if router credentials fail.
    }
  }

  const char* state() {
    return WiFi.status() == WL_CONNECTED ? "connected" : joining ? "joining" : "disconnected";
  }

  void status(Print& reply, bool includePassword = false) {
    JsonDocument data;
    data["protocol"] = "rover-wifi/1";
    data["ap_ready"] = apReady;
    data["ap_ssid"] = ssid;
    data["ap_ip"] = WiFi.softAPIP().toString();
    data["port"] = 5000;
    data["station_ssid"] = stationSSID;
    data["station_status"] = state();
    data["station_ip"] = WiFi.localIP().toString();
    if (includePassword) data["ap_password"] = password;
    serializeJson(data, reply);
    reply.println();
  }

  // Only called from USB, after stopping motors and dropping network ownership.
  void configure(const char* json, Print& reply) {
    JsonDocument data;
    if (deserializeJson(data, json) || !data["ssid"].is<const char*>() ||
        !data["password"].is<const char*>()) {
      reply.println("ERR WIFI_CONFIG");
      return;
    }
    String name = data["ssid"].as<String>();
    String pass = data["password"].as<String>();
    if (name.length() < 1 || name.length() > 32 || pass.length() > 63 ||
        (pass.length() != 0 && pass.length() < 8)) {
      reply.println("ERR WIFI_CONFIG_LENGTH");
      return;
    }
    Preferences settings;
    if (!settings.begin("rover-wifi", false)) {
      reply.println("ERR WIFI_SAVE");
      return;
    }
    // Invalidate SSID first so interrupted updates do not mix network credentials.
    settings.remove("sta-ssid");
    settings.putString("sta-pass", pass);
    settings.putString("sta-ssid", name);
    settings.end();
    WiFi.disconnect(false, false);
    stationSSID = name;
    startStation(pass);
    reply.println("OK WIFI_JOIN");
  }

  void forget(Print& reply) {
    Preferences settings;
    settings.begin("rover-wifi", false);
    settings.remove("sta-ssid");
    settings.remove("sta-pass");
    settings.end();
    WiFi.disconnect(false, false);
    stationSSID = "";
    joining = false;
    reply.println("OK WIFI_FORGET");
  }
};
