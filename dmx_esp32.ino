// -------------- INTERFAZ DMX A USB BASADA EN EL MOCROCONTROLADOR ESP32 -----------
// -------------- ESPINO MARCA MARY ISABEL ----------------------------------------
#include "driver/uart.h"
#include <EEPROM.h>

#define DMX_PIN_TX              17
#define DMX_PIN_HABILITAR       4
#define DMX_CANALES             512
#define MAX_ESCENAS             24
#define MAX_SECUENCIAS          23
#define MAX_LONGITUD_SECUENCIA  32
#define MAX_FIXTURES            2
#define CANALES_7               7
#define CANALES_23              23

// ------ Paso de secuencia multi-fixture -------------------------------------------
// Cada paso tiene una escena por fixture (0 = no aplicar ese fixture)
struct Paso {
  uint8_t escena[MAX_FIXTURES];  // escena[0]=F1, escena[1]=F2 (0=no cambiar)
};

// -------------- Estructura de la EEPROM --------------------------------------------
#define EEPROM_TAMANO           4096
#define EEPROM_MAGICO           0xAC   // cambiado de 0xAB para forzar re-init
#define EEPROM_ESCENA_CANALES   48
#define DIR_MAGICO              0
#define DIR_FIXTURE_CANALES     1
#define DIR_BASE0               2
#define DIR_BASE1               4
#define DIR_LONGITUD_SECUENCIA  6     // 20 bytes
#define DIR_SECUENCIA_GUARDADA  26    // 20 bytes
#define DIR_PASOS               46    // 20 * 32 * 2 = 1280 bytes (escena por fixture)
#define DIR_ESCENA_GUARDADA     1326  // 24 bytes
#define DIR_ESCENAS             1350  // 24 * 48 = 1152 bytes
// Total: ~2502 bytes < 4096 OK

// ------------- Variables globales ----------------------------------------------------
uint8_t  datosDMX[DMX_CANALES + 1];
uint8_t  escenas[MAX_ESCENAS][DMX_CANALES + 1];
bool     escenaGuardada[MAX_ESCENAS];

uint16_t fixtureBase[MAX_FIXTURES] = {1, 8};
uint8_t  fixtureCanales = CANALES_7;
int      fixtureActivo  = 0;

// Secuencias multi-fixture
Paso     secuencias[MAX_SECUENCIAS][MAX_LONGITUD_SECUENCIA];
uint8_t  longitudSecuencia[MAX_SECUENCIAS];
bool     secuenciaGuardada[MAX_SECUENCIAS];

bool     reproduciendo   = false;
int      secuenciaActiva = -1;
int      pasoActual      = 0;
int      duracionEscena  = 3000;

// Dimmer sostenido por fixture (controlado por los faders g1/g2).
// dimmerActivo[f] = el usuario ya tocó ese fader -> se fuerza el nivel,
uint8_t  nivelDimmer[MAX_FIXTURES];
bool     dimmerActivo[MAX_FIXTURES];

int      ultimoCanal = -1;
int      ultimoValor   = 0;
String   bufferSerial = "";

// -------------------- EEPROM -------------------------------------------------------
void guardarEEPROM() {
  EEPROM.write(DIR_MAGICO, EEPROM_MAGICO);
  EEPROM.write(DIR_FIXTURE_CANALES, fixtureCanales);
  EEPROM.write(DIR_BASE0,     fixtureBase[0] & 0xFF);
  EEPROM.write(DIR_BASE0 + 1, (fixtureBase[0] >> 8) & 0xFF);
  EEPROM.write(DIR_BASE1,     fixtureBase[1] & 0xFF);
  EEPROM.write(DIR_BASE1 + 1, (fixtureBase[1] >> 8) & 0xFF);

  for (int i = 0; i < MAX_SECUENCIAS; i++) {
    EEPROM.write(DIR_LONGITUD_SECUENCIA   + i, longitudSecuencia[i]);
    EEPROM.write(DIR_SECUENCIA_GUARDADA + i, secuenciaGuardada[i] ? 1 : 0);
    for (int j = 0; j < MAX_LONGITUD_SECUENCIA; j++) {
      int base = DIR_PASOS + (i * MAX_LONGITUD_SECUENCIA + j) * MAX_FIXTURES;
      for (int f = 0; f < MAX_FIXTURES; f++)
        EEPROM.write(base + f, secuencias[i][j].escena[f]);
    }
  }
  for (int i = 0; i < MAX_ESCENAS; i++) {
    EEPROM.write(DIR_ESCENA_GUARDADA + i, escenaGuardada[i] ? 1 : 0);
    for (int c = 0; c < EEPROM_ESCENA_CANALES; c++)
      EEPROM.write(DIR_ESCENAS + i * EEPROM_ESCENA_CANALES + c, escenas[i][c]);
  }
  EEPROM.commit();
  Serial.println("EEPROM OK");
}

bool cargarEEPROM() {
  if (EEPROM.read(DIR_MAGICO) != EEPROM_MAGICO) {
    Serial.println("EEPROM vacia - valores por defecto.");
    return false;
  }
  fixtureCanales = EEPROM.read(DIR_FIXTURE_CANALES);
  if (fixtureCanales != CANALES_7 && fixtureCanales != CANALES_23)
    fixtureCanales = CANALES_7;
  fixtureBase[0] = EEPROM.read(DIR_BASE0) | (EEPROM.read(DIR_BASE0+1) << 8);
  fixtureBase[1] = EEPROM.read(DIR_BASE1) | (EEPROM.read(DIR_BASE1+1) << 8);

  for (int i = 0; i < MAX_SECUENCIAS; i++) {
    longitudSecuencia[i]      = EEPROM.read(DIR_LONGITUD_SECUENCIA + i);
    secuenciaGuardada[i] = EEPROM.read(DIR_SECUENCIA_GUARDADA + i) == 1;
    for (int j = 0; j < MAX_LONGITUD_SECUENCIA; j++) {
      int base = DIR_PASOS + (i * MAX_LONGITUD_SECUENCIA + j) * MAX_FIXTURES;
      for (int f = 0; f < MAX_FIXTURES; f++)
        secuencias[i][j].escena[f] = EEPROM.read(base + f);
    }
  }
  for (int i = 0; i < MAX_ESCENAS; i++) {
    escenaGuardada[i] = EEPROM.read(DIR_ESCENA_GUARDADA + i) == 1;
    for (int c = 0; c < EEPROM_ESCENA_CANALES; c++)
      escenas[i][c] = EEPROM.read(DIR_ESCENAS + i * EEPROM_ESCENA_CANALES + c);
  }
  Serial.println("EEPROM cargada.");
  return true;
}

// ------------------ Estado para Python -------------------------------------
void enviarEstado() {
  Serial.println("STATE_BEGIN");
  Serial.printf("MODO=%d\n", fixtureCanales);
  Serial.printf("BASE=%d,%d\n", fixtureBase[0], fixtureBase[1]);
  Serial.printf("FIXTURE=%d\n", fixtureActivo + 1);
  Serial.printf("T=%d\n", duracionEscena);

  for (int i = 0; i < MAX_ESCENAS; i++)
    if (escenaGuardada[i])
      Serial.printf("ESCENA=%d\n", i + 1);

  for (int i = 0; i < MAX_SECUENCIAS; i++) {
    if (secuenciaGuardada[i] && longitudSecuencia[i] > 0) {
      // Formato: SEQ=G1,F1:S1+F2:S2,F1:S3+F2:S0,...
      Serial.printf("SEQ=G%d", i + 1);
      for (int j = 0; j < longitudSecuencia[i]; j++) {
        Serial.print(",");
        bool primero = true;
        for (int f = 0; f < MAX_FIXTURES; f++) {
          if (secuencias[i][j].escena[f] > 0) {
            if (!primero) Serial.print("+");
            Serial.printf("F%d:S%d", f+1, secuencias[i][j].escena[f]);
            primero = false;
          }
        }
      }
      Serial.println();
    }
  }

  for (int f = 0; f < MAX_FIXTURES; f++) {
    Serial.printf("FSTATE=%d", f + 1);
    for (int c = 0; c < fixtureCanales; c++)
      Serial.printf(",%d", datosDMX[fixtureBase[f] + c]);
    Serial.println();
  }
  Serial.println("STATE_END");
}

// ------------------ Funciones auxiliares de fixture ------------------------------
void fijarCanalFixture(int ch, uint8_t valor) {
  if (ch < 1 || ch > fixtureCanales) return;
  if (fixtureActivo == -1) {
    for (int f = 0; f < MAX_FIXTURES; f++) {
      int dmxCh = fixtureBase[f] + ch - 1;
      if (dmxCh >= 1 && dmxCh <= DMX_CANALES) {
        ultimoCanal = dmxCh; ultimoValor = datosDMX[dmxCh];
        datosDMX[dmxCh] = valor;
      }
    }
  } else {
    int dmxCh = fixtureBase[fixtureActivo] + ch - 1;
    if (dmxCh >= 1 && dmxCh <= DMX_CANALES) {
      ultimoCanal = dmxCh; ultimoValor = datosDMX[dmxCh];
      datosDMX[dmxCh] = valor;
    }
  }
}

void guardarEscenaFixture(int idx) {
  if (!escenaGuardada[idx]) memset(escenas[idx], 0, sizeof(escenas[idx]));
  if (fixtureActivo == -1) {
    memcpy(escenas[idx], datosDMX, sizeof(datosDMX));
  } else {
    int base = fixtureBase[fixtureActivo];
    for (int i = 0; i < fixtureCanales; i++)
      escenas[idx][base + i] = datosDMX[base + i];
  }
  escenaGuardada[idx] = true;
}

// Fija el nivel de dimmer de un fixture (0..255) y lo marca como activo.
//   - 7 canales:  escala R,G,B (no hay canal dimmer dedicado)
//   - 23 canales: fuerza el canal 1 (dimmer real)
void fijarDimmerFixture(int idx, uint8_t val) {
  if (idx < 0 || idx >= MAX_FIXTURES) return;
  nivelDimmer[idx]   = val;
  dimmerActivo[idx] = true;
}

// Aplica una escena a un fixture específico (sin tocar otros fixtures)
void aplicarEscenaAFixture(int escIdx, int fIdx) {
  int base = fixtureBase[fIdx];
  for (int i = 0; i < fixtureCanales; i++)
    datosDMX[base + i] = escenas[escIdx][base + i];
}

// ------------------ Reproducción de paso multi-fixture ----------------------------------
void reproducirPaso(int seqIdx, int paso) {
  Serial.printf("PASO=%d,T=%lu\n", paso, millis());
  for (int f = 0; f < MAX_FIXTURES; f++) {
    uint8_t esc = secuencias[seqIdx][paso].escena[f];
    if (esc >= 1 && esc <= MAX_ESCENAS && escenaGuardada[esc - 1])
      aplicarEscenaAFixture(esc - 1, f);
    // si esc == 0, ese fixture no se toca en este paso
  }
  // El dimmer se aplica al enviar (enviarDMX), así que el chase ya queda atenuado.
}

// ------------------- Configuración inicial -------------------------------------
void setup() {
  Serial.begin(115200);
  EEPROM.begin(EEPROM_TAMANO);
  memset(datosDMX, 0, sizeof(datosDMX));
  for (int i = 0; i < MAX_ESCENAS; i++) escenaGuardada[i] = false;
  for (int f = 0; f < MAX_FIXTURES; f++) {
    nivelDimmer[f]   = 255;     // arranca al máximo
    dimmerActivo[f] = false;   // hasta que se toque el fader g1/g2
  }
  for (int i = 0; i < MAX_SECUENCIAS; i++) {
    secuenciaGuardada[i] = false;
    longitudSecuencia[i] = 0;
    for (int j = 0; j < MAX_LONGITUD_SECUENCIA; j++)
      for (int f = 0; f < MAX_FIXTURES; f++)
        secuencias[i][j].escena[f] = 0;
  }
  cargarEEPROM();

  pinMode(DMX_PIN_HABILITAR, OUTPUT);
  digitalWrite(DMX_PIN_HABILITAR, HIGH);

  const uart_config_t uart_config = {
    .baud_rate = 250000, .data_bits = UART_DATA_8_BITS,
    .parity = UART_PARITY_DISABLE, .stop_bits = UART_STOP_BITS_2,
    .flow_ctrl = UART_HW_FLOWCTRL_DISABLE
  };
  uart_param_config(UART_NUM_1, &uart_config);
  uart_set_pin(UART_NUM_1, DMX_PIN_TX, UART_PIN_NO_CHANGE,
               UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
  uart_driver_install(UART_NUM_1, 1024, 0, 0, NULL, 0);

  Serial.printf("ESP32 DMX listo. F1=%d F2=%d modo=%dch\n",
                fixtureBase[0], fixtureBase[1], fixtureCanales);
}

// ------------------ Bucle principal -----------------------------------------
void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { procesarComandoSerial(bufferSerial); bufferSerial = ""; }
    else if (c != '\r') bufferSerial += c;
  }

  if (reproduciendo && secuenciaActiva >= 0 &&
      secuenciaGuardada[secuenciaActiva] &&
      longitudSecuencia[secuenciaActiva] > 0) {

    reproducirPaso(secuenciaActiva, pasoActual);

    unsigned long t0 = millis();
    while (millis() - t0 < (unsigned long)duracionEscena) {
      enviarDMX(); delay(25);
      // Seguir leyendo serial durante la espera:
      //   H      = detener
      //   T####  = cambiar la velocidad EN VIVO
      while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n') {
          String linea = bufferSerial;
          bufferSerial = "";
          if (linea.equalsIgnoreCase("H")) {
            reproduciendo = false; secuenciaActiva = -1; pasoActual = 0;
            Serial.println("Detenido.");
            return;
          } else if (linea.startsWith("T") && linea.length() > 1 &&
                     isDigit(linea.charAt(1))) {
            int t = linea.substring(1).toInt();
            if (t >= 100 && t <= 20000) {
              duracionEscena = t;
              Serial.printf("T=%dms (en vivo)\n", t);
            }
          } else if (linea.startsWith("D") && linea.length() > 2 &&
                     linea.indexOf(',') > 0) {
            int coma = linea.indexOf(',');
            int f    = linea.substring(1, coma).toInt();
            int val  = linea.substring(coma + 1).toInt();
            if (val < 0) val = 0; if (val > 255) val = 255;
            if (f == 0) { for (int i = 0; i < MAX_FIXTURES; i++) fijarDimmerFixture(i, (uint8_t)val); }
            else if (f >= 1 && f <= MAX_FIXTURES) fijarDimmerFixture(f - 1, (uint8_t)val);
          }
          // cualquier otro comando se ignora durante la reproducción
        } else if (c != '\r') bufferSerial += c;
      }
    }
    pasoActual = (pasoActual + 1) % longitudSecuencia[secuenciaActiva];
  } else {
    enviarDMX(); delay(25);
  }
}

void enviarDMX() {
  static uint8_t bufferSalida[DMX_CANALES + 1];
  memcpy(bufferSalida, datosDMX, DMX_CANALES + 1);

  // Aplicar el dimmer de cada fixture SOLO al enviar (no se toca datosDMX):
  //   - 7 canales:  no hay canal dimmer -> se escalan R, G, B (ch 1,2,3)
  //   - 23 canales: el dimmer real es el canal 1 -> se fuerza su valor
  for (int f = 0; f < MAX_FIXTURES; f++) {
    if (!dimmerActivo[f]) continue;
    int base = fixtureBase[f];
    if (fixtureCanales == CANALES_7) {
      for (int i = 0; i < 3; i++) {                 // R, G, B
        int ch = base + i;
        if (ch >= 1 && ch <= DMX_CANALES)
          bufferSalida[ch] = (uint16_t)datosDMX[ch] * nivelDimmer[f] / 255;
      }
    } else {
      int ch = base;                                // canal 1 = dimmer real
      if (ch >= 1 && ch <= DMX_CANALES)
        bufferSalida[ch] = nivelDimmer[f];
    }
  }
  bufferSalida[0] = 0;  // start code DMX

  uart_set_line_inverse(UART_NUM_1, UART_SIGNAL_TXD_INV);
  delayMicroseconds(110);
  uart_set_line_inverse(UART_NUM_1, UART_SIGNAL_INV_DISABLE);
  delayMicroseconds(12);
  uart_write_bytes(UART_NUM_1, (const char*)bufferSalida, DMX_CANALES + 1);
}

// ---------------- Analizador de comandos -----------------------------------
void procesarComandoSerial(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;

  if (cmd.equalsIgnoreCase("GETSTATE"))    { enviarEstado(); return; }
  if (cmd.equalsIgnoreCase("CLEAREEPROM")) {
    EEPROM.write(DIR_MAGICO, 0x00); EEPROM.commit();
    Serial.println("EEPROM borrada. Reinicia."); return;
  }

  if (cmd.equalsIgnoreCase("B")) {
    if (fixtureActivo == -1) { memset(datosDMX, 0, sizeof(datosDMX)); Serial.println("Todo borrado."); }
    else {
      int base = fixtureBase[fixtureActivo];
      for (int i = 0; i < fixtureCanales; i++) datosDMX[base+i] = 0;
      Serial.printf("F%d borrado.\n", fixtureActivo+1);
    }
    return;
  }

  if (cmd.equalsIgnoreCase("V")) {
    if (ultimoCanal >= 1) { datosDMX[ultimoCanal] = ultimoValor; Serial.printf("Undo ch%d=%d\n", ultimoCanal, ultimoValor); }
    return;
  }

  if (cmd.equalsIgnoreCase("H")) {
    reproduciendo = false; secuenciaActiva = -1; pasoActual = 0;
    Serial.println("Detenido."); return;
  }

  if (cmd.equalsIgnoreCase("MODE7")) {
    fixtureCanales = CANALES_7; fixtureBase[0]=1; fixtureBase[1]=8;
    guardarEEPROM(); Serial.println("Modo 7ch. F1=1-7 F2=8-14"); return;
  }
  if (cmd.equalsIgnoreCase("MODE23")) {
    fixtureCanales = CANALES_23; fixtureBase[0]=1; fixtureBase[1]=24;
    guardarEEPROM(); Serial.println("Modo 23ch. F1=1-23 F2=24-46"); return;
  }

  // F# seleccionar fixture
  if (cmd.startsWith("F") && cmd.length() <= 3 && isDigit(cmd.charAt(1))) {
    int n = cmd.substring(1).toInt();
    if (n == 0) { fixtureActivo = -1; Serial.println("Fixture: AMBOS"); }
    else if (n >= 1 && n <= MAX_FIXTURES) {
      fixtureActivo = n-1;
      Serial.printf("F%d activo (ch%d-%d)\n", n, fixtureBase[n-1], fixtureBase[n-1]+fixtureCanales-1);
    }
    return;
  }

  // A#=dir
  if (cmd.startsWith("A") && cmd.indexOf('=') != -1) {
    int eq = cmd.indexOf('=');
    int fn = cmd.substring(1, eq).toInt();
    int dir = cmd.substring(eq+1).toInt();
    if (fn >= 1 && fn <= MAX_FIXTURES && dir >= 1) {
      fixtureBase[fn-1] = dir; guardarEEPROM();
      Serial.printf("F%d base=%d\n", fn, dir);
    }
    return;
  }

  // S# guardar escena
  if (cmd.startsWith("S") && isDigit(cmd.charAt(1))) {
    int n = cmd.substring(1).toInt();
    if (n >= 1 && n <= MAX_ESCENAS) {
      guardarEscenaFixture(n-1); guardarEEPROM();
      Serial.printf("Escena %d guardada.\n", n);
    }
    return;
  }

  // P# reproducir escena
  if (cmd.startsWith("P") && isDigit(cmd.charAt(1))) {
    int n = cmd.substring(1).toInt();
    if (n >= 1 && n <= MAX_ESCENAS && escenaGuardada[n-1]) {
      if (fixtureActivo == -1) memcpy(datosDMX, escenas[n-1], sizeof(datosDMX));
      else aplicarEscenaAFixture(n-1, fixtureActivo);
      Serial.printf("Escena %d reproducida.\n", n);
    }
    return;
  }

  // G# o G#=pasos
  if (cmd.startsWith("G")) {
    int eq = cmd.indexOf('=');
    if (eq != -1) {
      int gnum = cmd.substring(1, eq).toInt();
      if (gnum >= 1 && gnum <= MAX_SECUENCIAS) {
        // Resetear secuencia
        for (int j = 0; j < MAX_LONGITUD_SECUENCIA; j++)
          for (int f = 0; f < MAX_FIXTURES; f++)
            secuencias[gnum-1][j].escena[f] = 0;

        int len = 0;
        String pasos = cmd.substring(eq + 1);
        int start = 0;

        while (start < (int)pasos.length() && len < MAX_LONGITUD_SECUENCIA) {
          int comma = pasos.indexOf(',', start);
          String paso = (comma == -1) ? pasos.substring(start)
                                      : pasos.substring(start, comma);
          paso.trim();

          // Formato extendido: "F1:S3+F2:S5"
          if (paso.indexOf(':') != -1) {
            int plus = 0, pstart = 0;
            while (pstart < (int)paso.length()) {
              int pend = paso.indexOf('+', pstart);
              String seg = (pend == -1) ? paso.substring(pstart)
                                        : paso.substring(pstart, pend);
              // seg = "F1:S3"
              int col = seg.indexOf(':');
              if (col != -1 && seg.charAt(0) == 'F') {
                int fIdx = seg.substring(1, col).toInt() - 1;
                int sNum = seg.substring(col + 2).toInt(); // skip 'S'
                if (fIdx >= 0 && fIdx < MAX_FIXTURES && sNum >= 1 && sNum <= MAX_ESCENAS)
                  secuencias[gnum-1][len].escena[fIdx] = (uint8_t)sNum;
              }
              if (pend == -1) break;
              pstart = pend + 1;
            }
          }
          // Formato simple: solo número de escena (aplicar al fixture activo)
          else {
            int sNum = paso.toInt();
            if (sNum >= 1 && sNum <= MAX_ESCENAS) {
              int fIdx = (fixtureActivo == -1) ? 0 : fixtureActivo;
              secuencias[gnum-1][len].escena[fIdx] = (uint8_t)sNum;
            }
          }
          len++;
          if (comma == -1) break;
          start = comma + 1;
        }

        if (len > 0) {
          longitudSecuencia[gnum-1] = len;
          secuenciaGuardada[gnum-1] = true;
          guardarEEPROM();
          Serial.printf("G%d guardada (%d pasos) EEPROM OK\n", gnum, len);
        }
      }
    } else {
      // Ejecutar G#
      int gnum = cmd.substring(1).toInt();
      if (gnum >= 1 && gnum <= MAX_SECUENCIAS &&
          secuenciaGuardada[gnum-1] && longitudSecuencia[gnum-1] > 0) {
        secuenciaActiva = gnum-1; pasoActual = 0; reproduciendo = true;
        Serial.printf("Bucle G%d (T=%dms)\n", gnum, duracionEscena);
      } else Serial.println("G# no programada.");
    }
    return;
  }

  // T####
  if (cmd.startsWith("T") && cmd.length() > 1 && isDigit(cmd.charAt(1))) {
    int t = cmd.substring(1).toInt();
    if (t >= 100 && t <= 20000) { duracionEscena = t; Serial.printf("T=%dms\n", t); }
    return;
  }

  // D{f},{val} -> dimmer del fixture f (1 o 2; 0 = ambos)
  if (cmd.startsWith("D") && cmd.length() > 2 && cmd.indexOf(',') > 0) {
    int coma = cmd.indexOf(',');
    int f    = cmd.substring(1, coma).toInt();
    int val  = cmd.substring(coma + 1).toInt();
    if (val < 0) val = 0; if (val > 255) val = 255;
    if (f == 0) {
      for (int i = 0; i < MAX_FIXTURES; i++) fijarDimmerFixture(i, (uint8_t)val);
      Serial.printf("Dimmer AMBOS=%d\n", val);
    } else if (f >= 1 && f <= MAX_FIXTURES) {
      fijarDimmerFixture(f - 1, (uint8_t)val);
      Serial.printf("Dimmer F%d=%d\n", f, val);
    }
    return;
  }

  // ch,val[:ch,val...]
  int start = 0;
  while (start < (int)cmd.length()) {
    int sep = cmd.indexOf(':', start);
    String part = (sep==-1) ? cmd.substring(start) : cmd.substring(start, sep);
    int comma = part.indexOf(',');
    if (comma != -1) {
      int ch = part.substring(0, comma).toInt();
      int val = part.substring(comma+1).toInt();
      if (ch >= 1 && ch <= fixtureCanales && val >= 0 && val <= 255) {
        fijarCanalFixture(ch, (uint8_t)val);
        Serial.printf("F%s ch%d=%d\n",
          fixtureActivo==-1?"ALL":String(fixtureActivo+1).c_str(), ch, val);
      }
    }
    if (sep == -1) break;
    start = sep + 1;
  }
}
