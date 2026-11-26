/*
 * Firmware da máquina M-06: ESP32 com sensores reais (simulado no Wokwi).
 *
 * Segue o MESMO contrato MQTT do simulador Python (contrato/README.md):
 *   <PREFIXO>fabrica/maquinas/M-06/telemetria  publica a leitura dos sensores (1 s)
 *   <PREFIXO>fabrica/maquinas/M-06/status      online/offline (retido; offline via Last Will)
 *   <PREFIXO>fabrica/maquinas/M-06/evento      manutenção realizada
 *   <PREFIXO>fabrica/maquinas/M-06/comando     (assina) ordens da plataforma
 *   <PREFIXO>fabrica/alertas                   (assina) acende o LED vermelho se a IA alertar ESTA máquina
 *
 * O Wokwi no navegador só alcança a internet, então o ESP32 fala com um broker
 * público. Um bridge do Mosquitto local espelha estes tópicos (sem o prefixo)
 * para a plataforma: ver README desta pasta.
 *
 * Sensores:
 *   DHT22 (GPIO 15)            temperatura do ar
 *   NTC   (GPIO 32)            temperatura do processo
 *   Potenciômetro (GPIO 34)    célula de carga -> torque (0-80 N·m)
 *   Potenciômetro (GPIO 35)    tacômetro       -> rotação (1000-2500 rpm)
 *   Botão (GPIO 4)             troca de ferramenta feita pelo operador
 *   LED verde (GPIO 27)        conectado à plataforma
 *   LED vermelho (GPIO 26)     alerta de manutenção da IA
 */
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHTesp.h>
#include <sys/time.h>
#include <time.h>

// ---------------- Configuração ----------------
#define WIFI_SSID      "Wokwi-GUEST"
#define WIFI_SENHA     ""
#define MQTT_BROKER    "broker.hivemq.com"
#define MQTT_PORTA     1883
// Prefixo único para não colidir com outros usuários do broker público.
// Deve ser IGUAL ao de mosquitto/mosquitto-wokwi.conf.
#define PREFIXO        "iotpm-d38091/"
#define MAQUINA_ID     "M-06"
#define TIPO_PRODUTO   "L"
#define INTERVALO_MS   1000   // uma leitura por segundo
#define DESGASTE_POR_LEITURA 2.0  // min de desgaste da ferramenta por leitura (acelerado para a demo)

#define PINO_DHT       15
#define PINO_NTC       32
#define PINO_TORQUE    34
#define PINO_ROTACAO   35
#define PINO_BOTAO     4
#define PINO_LED_OK    27
#define PINO_LED_ALERTA 26

#define TOPICO(sufixo) PREFIXO "fabrica/maquinas/" MAQUINA_ID "/" sufixo
const char* T_TELEMETRIA = TOPICO("telemetria");
const char* T_STATUS     = TOPICO("status");
const char* T_EVENTO     = TOPICO("evento");
const char* T_COMANDO    = TOPICO("comando");
const char* T_ALERTAS    = PREFIXO "fabrica/alertas";

WiFiClient wifi;
PubSubClient mqtt(wifi);
DHTesp dht;

float desgasteMin = 0;          // tempo de uso da ferramenta atual (contado pelo firmware)
unsigned long ultimaLeitura = 0;
bool emAlerta = false;

// ---------------- Utilidades ----------------
double agora() {  // epoch em segundos (relógio sincronizado por NTP)
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  return tv.tv_sec + tv.tv_usec / 1e6;
}

String json(JsonDocument& doc) {
  String s;
  serializeJson(doc, s);
  return s;
}

String statusPayload(const char* status, const char* motivo) {
  JsonDocument doc;
  doc["maquina_id"] = MAQUINA_ID;
  doc["ts"] = agora();
  doc["status"] = status;
  doc["motivo"] = motivo;
  return json(doc);
}

void publicarEvento(const char* evento, const char* detalhe) {
  JsonDocument doc;
  doc["maquina_id"] = MAQUINA_ID;
  doc["ts"] = agora();
  doc["evento"] = evento;
  doc["detalhe"] = detalhe;
  mqtt.publish(T_EVENTO, json(doc).c_str());
}

void trocarFerramenta(const char* origem) {
  desgasteMin = 0;
  emAlerta = false;
  digitalWrite(PINO_LED_ALERTA, LOW);
  publicarEvento("manutencao", "preventiva");
  Serial.printf("Ferramenta trocada (%s): desgaste zerado\n", origem);
}

// Termistor NTC do Wokwi (beta 3950, ADC de 12 bits do ESP32)
float lerNtcCelsius() {
  const float BETA = 3950;
  int adc = analogRead(PINO_NTC);
  return 1 / (log(1 / (4095. / adc - 1)) / BETA + 1.0 / 298.15) - 273.15;
}

// ---------------- MQTT ----------------
void aoReceber(char* topico, byte* payload, unsigned int tamanho) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, tamanho)) return;  // ignora JSON inválido

  if (strcmp(topico, T_COMANDO) == 0 && doc["acao"] == "manutencao") {
    trocarFerramenta("comando da plataforma");
  } else if (strcmp(topico, T_ALERTAS) == 0 && doc["maquina_id"] == MAQUINA_ID) {
    emAlerta = true;
    digitalWrite(PINO_LED_ALERTA, HIGH);
    Serial.printf("ALERTA da IA: %s\n", doc["mensagem"].as<const char*>());
  }
}

void conectarMqtt() {
  while (!mqtt.connected()) {
    digitalWrite(PINO_LED_OK, LOW);
    String clientId = String("iotpm-esp32-") + MAQUINA_ID + "-" + String((uint32_t)esp_random(), HEX);
    String testamento = statusPayload("offline", "conexao_perdida");
    Serial.print("Conectando ao broker MQTT... ");
    // Last Will: se a conexão cair, o BROKER publica 'offline' (retido) por nós
    if (mqtt.connect(clientId.c_str(), T_STATUS, 1, true, testamento.c_str())) {
      Serial.println("ok");
      mqtt.publish(T_STATUS, statusPayload("online", "").c_str(), true);  // retido
      mqtt.subscribe(T_COMANDO, 1);
      mqtt.subscribe(T_ALERTAS, 1);
      digitalWrite(PINO_LED_OK, HIGH);
    } else {
      Serial.printf("falhou (rc=%d), tentando de novo em 2 s\n", mqtt.state());
      delay(2000);
    }
  }
}

// ---------------- Programa ----------------
void setup() {
  Serial.begin(115200);
  pinMode(PINO_BOTAO, INPUT_PULLUP);
  pinMode(PINO_LED_OK, OUTPUT);
  pinMode(PINO_LED_ALERTA, OUTPUT);
  dht.setup(PINO_DHT, DHTesp::DHT22);

  Serial.print("Conectando ao Wi-Fi");
  WiFi.begin(WIFI_SSID, WIFI_SENHA, 6);
  while (WiFi.status() != WL_CONNECTED) { delay(250); Serial.print("."); }
  Serial.println(" ok");

  // Relógio real via NTP. Se não sincronizar em 15 s (rede bloqueando NTP, por
  // exemplo), segue assim mesmo: o SNTP continua tentando em segundo plano e a
  // plataforma usa o horário de recebimento enquanto o relógio estiver errado.
  configTime(0, 0, "pool.ntp.org", "time.google.com", "time.cloudflare.com");
  Serial.print("Sincronizando relógio (NTP)");
  unsigned long inicioNtp = millis();
  while (time(nullptr) < 1700000000 && millis() - inicioNtp < 15000) { delay(250); Serial.print("."); }
  Serial.println(time(nullptr) >= 1700000000 ? " ok" : " sem NTP por enquanto (seguindo)");

  mqtt.setServer(MQTT_BROKER, MQTT_PORTA);
  mqtt.setBufferSize(512);
  mqtt.setCallback(aoReceber);
}

void loop() {
  if (!mqtt.connected()) conectarMqtt();
  mqtt.loop();

  if (digitalRead(PINO_BOTAO) == LOW) {  // operador trocou a ferramenta
    trocarFerramenta("botão do operador");
    delay(300);  // debounce
  }

  if (millis() - ultimaLeitura < INTERVALO_MS) return;
  ultimaLeitura = millis();

  float tempArC = dht.getTemperature();
  if (isnan(tempArC)) { Serial.println("Falha lendo o DHT22"); return; }

  desgasteMin += DESGASTE_POR_LEITURA;

  JsonDocument doc;
  doc["maquina_id"] = MAQUINA_ID;
  doc["ts"] = agora();
  doc["tipo"] = TIPO_PRODUTO;
  doc["temp_ar_k"] = roundf((tempArC + 273.15) * 100) / 100;
  doc["temp_processo_k"] = roundf((lerNtcCelsius() + 273.15) * 100) / 100;
  doc["rotacao_rpm"] = roundf(map(analogRead(PINO_ROTACAO), 0, 4095, 1000, 2500));
  doc["torque_nm"] = roundf(analogRead(PINO_TORQUE) / 4095.0 * 80 * 100) / 100;
  doc["desgaste_min"] = desgasteMin;

  String payload = json(doc);
  mqtt.publish(T_TELEMETRIA, payload.c_str());
  Serial.println(payload);
}
