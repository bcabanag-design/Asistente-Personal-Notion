# Documentación: Asistente Personal Notion (Telegram Bot)

## 📌 Descripción General
Este proyecto es un **Bot de Telegram inteligente** conectado a una base de datos de **Notion**. Permite gestionar tareas, recordatorios y listas de compras utilizando **lenguaje natural**, tanto por texto como por mensajes de voz.

La aplicación está construida en **Python (Flask)** y desplegada en **Render**.

---

## 🚀 Funcionalidades Principales

### 1. Gestión de Tareas y Recordatorios
El bot detecta intenciones de crear tareas y extrae fechas y horas automáticamente.
*   **Ejemplo**: _"Recordarme pagar la luz mañana a las 3pm"_
*   **Acción**: Crea una tarea en Notion con fecha "Mañana 15:00".

#### Características Avanzadas de Parsing:
*   **Fechas Relativas**: Entiende "mañana", "el lunes", "en 2 horas".
*   **Hora de Recordatorio Explícita**: Si dices _"Entrevista a las 10am avisarme a las 6am"_, separará la hora del evento (10:00) de la hora de la notificación (06:00).
*   **Protección de Contexto**: Distingue entre _"a las 10 de la mañana"_ (hora) y _"mañana"_ (día siguiente).

### 2. Listas Inteligentes
Permite agregar ítems rápidamente a listas específicas (ej. Mercado, Farmacia, Pendientes).
*   **Sintaxis 1 (Atajo)**: _"@Mercado comprar leche"_
*   **Sintaxis 2 (Natural)**: _"Leche para la lista de mercado"_
*   **Sintaxis 3 (Sufijo)**: _"Leche lista mercado"_

### 3. Consultas (Consultar Agenda y Listas)
Puedes preguntarle al bot qué tienes pendiente.
*   **Agenda**: _"¿Qué tengo para hoy?"_, _"Agenda del lunes"_
*   **Listas**: _"Ver lista mercado"_, _"Mostrar lista farmacia"_

### 4. Sistema de Posponer (Snooze)
Cuando recibes un recordatorio, el bot envía un botón de **"Posponer"**.
*   Al hacer clic, el bot pregunta: _"¿Para cuándo?"_.
*   Puedes responder natural: _"En 1 hora"_, _"Mañana a las 9"_.
*   El sistema actualiza la fecha en Notion automáticamente.

---

## 🛠️ Arquitectura Técnica

### Componentes
*   **Servidor**: Flask (Python) manejando Webhooks.
*   **Base de Datos**: Notion (vía Notion API).
*   **Mensajería**: Telegram Bot API.
*   **Procesamiento de Voz**: OpenAI Whisper (o librería `SpeechRecognition` local según configuración) + `pydub`.
*   **Parsing de Fechas**: Librería `dateparser` + Regex personalizados para español.

### Archivos Clave
*   `apag_asistente.py`: **Núcleo del sistema**. Contiene toda la lógica de rutas, webhooks y procesamiento de lenguaje natural.
*   `requirements.txt`: Dependencias del proyecto.
*   `.env`: Variables de entorno (Tokens de Notion y Telegram).

---

## 🔄 Flujo de Datos

1.  **Usuario** envía mensaje (texto/voz) a Telegram.
2.  **Telegram** envía un Webhook POST a la aplicación en Render.
3.  **Flask** recibe el mensaje en `apag_asistente.py`.
4.  **Lógica de Procesamiento**:
    *   Convierte audio a texto (si es voz).
    *   Analiza el texto con Regex y `dateparser`.
    *   Determina si es Tarea, Lista o Consulta.
5.  **Notion API**: Se ejecuta la acción (Create/Query/Update) en la base de datos de Notion.
6.  **Respuesta**: El bot confirma la acción al usuario en Telegram.

---

## 📱 Integración con Tasker (Android)

Sí, el proyecto está diseñado para recibir comandos desde **Tasker** u otras herramientas de automatización.

### Endpoint: `/agendar`
Se utiliza para enviar comandos de texto directamente al cerebro del asistente sin usar Telegram.

*   **URL**: `https://<tu-app-en-render>.onrender.com/agendar`
*   **Método**: `POST`
*   **Headers**: `Content-Type: application/json`
*   **Body (JSON)**:
    ```json
    {
      "comando": "Recordarme comprar pan mañana a las 8am"
    }
    ```

Esto permite crear tareas desde accesos directos en el celular, widgets, o rutinas de voz de Android que envíen este HTTP Request.

---

## 📦 Despliegue y Actualización

El proyecto está alojado en **Render** conectado a un repositorio **GitHub**.

### Cómo actualizar el código:
Si haces cambios locales en tu computadora:
1.  **Guardar cambios**: Asegúrate de que los archivos están guardados.
2.  **Enviar a GitHub**:
    ```bash
    git add .
    git commit -m "Descripción de los cambios"
    git push origin main
    ```
3.  **Render**: Detectará automáticamente el `push` y comenzará a reconstruir la aplicación (tarda ~2-3 minutos).
