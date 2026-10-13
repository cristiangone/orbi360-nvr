// Preguntas frecuentes del asistente de Orbi360 NVR (opción C: respuestas
// fijas, sin IA). Más adelante el asistente consultará un LLM propio y usará
// este contenido como base. Texto en español: es el idioma de los clientes.

export type FaqLink = {
  label: string;
  to: string;
};

export type FaqEntry = {
  id: string;
  category: string;
  question: string;
  // párrafos; **negrita** se muestra resaltado
  answer: string[];
  keywords: string[];
  link?: FaqLink;
};

export const FAQ_CATEGORIES = [
  "Primeros pasos",
  "Cámaras",
  "Grabaciones y alertas",
  "Mosaicos y transmisión",
  "Avisos",
  "Inteligencia artificial",
  "Problemas comunes",
] as const;

export const FAQ: FaqEntry[] = [
  {
    id: "que-es",
    category: "Primeros pasos",
    question: "¿Qué es Orbi360 NVR?",
    answer: [
      "Es el grabador de video de Orbi360: recibe las cámaras de tu red, **graba**, detecta **personas y autos con inteligencia artificial**, te **avisa** y puede **transmitir un mosaico** de cámaras a la plataforma de televisión.",
      "Funciona en un equipo dentro de tu red; las imágenes no salen a Internet salvo los mosaicos que tú configures.",
    ],
    keywords: ["producto", "servicio", "nvr", "grabador", "que hace"],
  },
  {
    id: "acceder",
    category: "Primeros pasos",
    question: "¿Cómo entro al sistema?",
    answer: [
      "Desde un navegador en la misma red, abre **https://IP-del-equipo:8971** (por ejemplo https://192.168.1.241:8971). El navegador avisará que el certificado no es de confianza: es normal, acepta la advertencia.",
      "Usuario **admin** y la clave que te entregó el técnico. Puedes cambiarla en Ajustes → Usuarios.",
    ],
    keywords: [
      "entrar",
      "login",
      "acceso",
      "clave",
      "contraseña",
      "usuario",
      "certificado",
      "8971",
    ],
    link: { label: "Ir a Usuarios", to: "/settings?page=users" },
  },
  {
    id: "celular",
    category: "Primeros pasos",
    question: "¿Puedo verlo desde el celular?",
    answer: [
      "Sí: abre la misma dirección en el navegador del celular conectado a tu WiFi. Puedes agregarlo a la pantalla de inicio desde el menú del navegador para usarlo como una app.",
      "Fuera de casa se necesita un acceso remoto (VPN) que configura el técnico.",
    ],
    keywords: [
      "celular",
      "movil",
      "telefono",
      "app",
      "remoto",
      "fuera de casa",
    ],
  },
  {
    id: "agregar-camara",
    category: "Cámaras",
    question: "¿Cómo agrego una cámara nueva?",
    answer: [
      "Conecta la cámara a la misma red WiFi o cable. En unos 3 minutos aparece en **Ajustes → Red de cámaras → Cámaras nuevas detectadas** (también te avisa por Telegram si está activado).",
      "Presiona **Agregar**, escribe un nombre (por ejemplo «Patio») y **Detectar**. Orbi360 la configura, la graba y la sigue aunque cambie de IP. El NVR se reinicia y la cámara aparece en 1-2 minutos.",
      "Si la cámara no aparece, usa **Agregar cámara por IP**. Para otras marcas activa «Otra marca» y escribe sus URLs RTSP.",
    ],
    keywords: [
      "agregar",
      "añadir",
      "nueva",
      "camara nueva",
      "instalar",
      "conectar",
    ],
    link: { label: "Ir a Red de cámaras", to: "/settings?page=cameraNetwork" },
  },
  {
    id: "clave-camara",
    category: "Cámaras",
    question: "La cámara nueva pide clave o no la acepta",
    answer: [
      "Orbi360 entra a las cámaras con una clave común guardada en el equipo. Las cámaras iCSee nuevas vienen **sin clave local** aunque la app iCSee muestre una: el técnico se la pone con el comando `xmcam passwd`.",
      "Si al detectar aparece «no acepta la clave de Orbi360», pide al técnico que corra ese comando con la IP de la cámara.",
    ],
    keywords: ["clave", "contraseña", "icsee", "no acepta", "203", "dvrip"],
  },
  {
    id: "sub-stream",
    category: "Cámaras",
    question: "¿Qué significa «_sub» (por ejemplo cocina_sub)?",
    answer: [
      "Cada cámara envía dos videos: el **principal** (alta resolución) para **grabar** y ver en grande, y el **secundario** («_sub», baja resolución) para la **detección con IA**, las miniaturas y los mosaicos.",
      "Así la IA trabaja liviana y la grabación conserva la calidad. No borres los «_sub»: la cámara deja de detectar.",
    ],
    keywords: [
      "sub",
      "_sub",
      "secundario",
      "principal",
      "stream",
      "flujo",
      "go2rtc",
    ],
    link: {
      label: "Ver flujos go2rtc",
      to: "/settings?page=systemGo2rtcStreams",
    },
  },
  {
    id: "cambio-ip",
    category: "Cámaras",
    question: "La cámara cambió de IP, ¿tengo que hacer algo?",
    answer: [
      "No. Orbi360 sigue a cada cámara por su **MAC** (su identificador físico): si el router le da otra IP, el NVR la actualiza solo en menos de 3 minutos y te avisa.",
      "En Ajustes → Red de cámaras ves la IP y el estado de cada una.",
    ],
    keywords: ["ip", "cambio de ip", "dhcp", "router", "mac", "red"],
    link: { label: "Ir a Red de cámaras", to: "/settings?page=cameraNetwork" },
  },
  {
    id: "repetidor",
    category: "Cámaras",
    question: "Mi cámara dice «Detrás de repetidor»",
    answer: [
      "Está conectada a un **repetidor WiFi** que muestra su propia MAC en lugar de la de la cámara. Orbi360 la graba igual, pero **no puede seguirla** si el router le cambia la IP.",
      "Lo ideal es conectarla al **router principal** (o poner el repetidor en modo punto de acceso). Si no se puede, fija su IP en el router.",
    ],
    keywords: ["repetidor", "extensor", "tp-link", "mac", "bridged", "wifi"],
    link: { label: "Ir a Red de cámaras", to: "/settings?page=cameraNetwork" },
  },
  {
    id: "sin-senal",
    category: "Problemas comunes",
    question: "Una cámara dice «sin señal» o «transmisión desconectada»",
    answer: [
      "Revisa en orden: 1) que la cámara tenga **energía** (luz encendida); 2) que tenga **WiFi** (¿se ve en su app?); 3) su estado en **Ajustes → Red de cámaras**: «No vista» es energía o WiFi, «IP compartida» es un choque de IP en el router.",
      "Si en la app de la cámara se ve pero aquí no, avisa al técnico: puede ser la clave o el formato de video.",
    ],
    keywords: [
      "sin señal",
      "desconectada",
      "no se ve",
      "negro",
      "caida",
      "offline",
      "no frames",
    ],
    link: { label: "Ir a Red de cámaras", to: "/settings?page=cameraNetwork" },
  },
  {
    id: "grabaciones-donde",
    category: "Grabaciones y alertas",
    question: "¿Dónde veo lo que grabó?",
    answer: [
      "En **Revisión** (ícono de reproducción) ves las **alertas** del día (personas, autos) y puedes ir hacia atrás en la línea de tiempo de cada cámara.",
      "En **Explorar** buscas por objeto, cámara o fecha.",
    ],
    keywords: [
      "grabaciones",
      "grabado",
      "ver",
      "historial",
      "revision",
      "pasado",
      "video",
    ],
    link: { label: "Ir a Revisión", to: "/review" },
  },
  {
    id: "cuanto-guarda",
    category: "Grabaciones y alertas",
    question: "¿Cuántos días guarda?",
    answer: [
      "Lo normal es **7 días**. Se puede guardar solo las **alertas de IA** (personas, autos), todo lo que tenga **movimiento**, o **continuo** las 24 horas. Con alertas o movimiento, 7 días de 4 a 8 cámaras ocupan pocas decenas de GB.",
      "Lo más antiguo se borra solo cuando se cumple el plazo.",
    ],
    keywords: [
      "dias",
      "retencion",
      "cuanto",
      "guarda",
      "borra",
      "disco",
      "espacio",
    ],
    link: { label: "Ver grabación", to: "/settings?page=globalRecording" },
  },
  {
    id: "exportar",
    category: "Grabaciones y alertas",
    question: "¿Cómo descargo un video?",
    answer: [
      "Abre la grabación en Revisión, elige el tramo con el ícono de **exportar** y espera a que termine. Los videos quedan en **Exportaciones**, desde donde se descargan.",
    ],
    keywords: ["descargar", "exportar", "bajar", "video", "clip", "guardar"],
    link: { label: "Ir a Exportaciones", to: "/export" },
  },
  {
    id: "mosaico",
    category: "Mosaicos y transmisión",
    question: "¿Qué es un mosaico SRT?",
    answer: [
      "Es una imagen con varias cámaras juntas (2×2, 3×3…) que Orbi360 transmite por **SRT** a un servidor, por ejemplo la plataforma de TV, para verlas como un canal.",
      "Se configuran en **Ajustes → Mosaico SRT**: cámaras, resolución, calidad y destino («Enviar a»). Una cámara caída aparece en gris con «SIN SEÑAL» y el resto sigue transmitiendo.",
    ],
    keywords: [
      "mosaico",
      "srt",
      "canal",
      "tv",
      "transmitir",
      "television",
      "miraime",
    ],
    link: { label: "Ir a Mosaico SRT", to: "/settings?page=srtMosaics" },
  },
  {
    id: "mosaico-no-llega",
    category: "Mosaicos y transmisión",
    question: "El canal del mosaico no llega al servidor",
    answer: [
      "En Ajustes → Mosaico SRT mira el estado: **Conectado** quiere decir que la conexión está abierta. Si dice conectado pero el servidor recibe 0, la sesión quedó colgada en el servidor: usa el botón de **reiniciar** del mosaico.",
      "Además, cada mosaico se reconecta solo todos los días a las 4:00.",
    ],
    keywords: [
      "no llega",
      "conectando",
      "0 kbps",
      "mosaico",
      "servidor",
      "srt",
      "caido",
    ],
    link: { label: "Ir a Mosaico SRT", to: "/settings?page=srtMosaics" },
  },
  {
    id: "telegram",
    category: "Avisos",
    question: "¿Cómo recibo avisos en Telegram?",
    answer: [
      "En **Ajustes → Mosaico SRT → Avisos por Telegram** ingresa el token de tu bot y tu ID de chat, activa los avisos y usa **Probar**. Recibirás avisos de mosaicos caídos, cámaras que cambian de IP y cámaras nuevas.",
    ],
    keywords: [
      "telegram",
      "avisos",
      "alertas",
      "notificaciones",
      "bot",
      "mensaje",
    ],
    link: { label: "Ir a Mosaico SRT", to: "/settings?page=srtMosaics" },
  },
  {
    id: "notificaciones",
    category: "Avisos",
    question: "¿Puedo recibir una notificación cuando detecta una persona?",
    answer: [
      "Sí, con las notificaciones del navegador: en **Ajustes → Notificaciones** actívalas en cada celular o PC y elige las cámaras. Llegan con la imagen de la alerta.",
    ],
    keywords: ["notificacion", "push", "persona", "intruso", "alerta", "aviso"],
    link: { label: "Ir a Notificaciones", to: "/settings?page=notifications" },
  },
  {
    id: "ia-que-detecta",
    category: "Inteligencia artificial",
    question: "¿Qué detecta la inteligencia artificial?",
    answer: [
      "Por defecto **personas y autos**. Cada detección queda como alerta con su imagen. Se pueden agregar otros objetos (perros, gatos, motos…) y **zonas** para avisar solo si alguien entra a un área.",
      "La IA corre dentro del equipo: no envía imágenes a Internet.",
    ],
    keywords: [
      "ia",
      "inteligencia",
      "detecta",
      "persona",
      "auto",
      "objetos",
      "zonas",
    ],
    link: { label: "Ver objetos", to: "/settings?page=globalObjects" },
  },
  {
    id: "busqueda",
    category: "Inteligencia artificial",
    question: "¿Puedo buscar con palabras, por ejemplo «persona con mochila»?",
    answer: [
      "Sí: en **Explorar** escribe lo que buscas. La búsqueda semántica compara tu texto con las imágenes de las detecciones.",
    ],
    keywords: [
      "buscar",
      "busqueda",
      "semantica",
      "explorar",
      "palabras",
      "descripcion",
    ],
    link: { label: "Ir a Explorar", to: "/explore" },
  },
  {
    id: "patentes",
    category: "Inteligencia artificial",
    question: "¿Cómo activo el reconocimiento de patentes?",
    answer: [
      "Primero se activa **para todo el sistema** en **Ajustes → Análisis avanzado → Reconocimiento de matrículas**; después, en la cámara que mira los autos. Si se activa solo en la cámara, al guardar da error.",
      "Funciona cuando la patente se ve **grande** en la imagen: una cámara dedicada que apunte a la entrada de vehículos, a pocos metros.",
    ],
    keywords: ["patente", "patentes", "matricula", "lpr", "placa", "autos"],
    link: {
      label: "Ir a Reconocimiento de matrículas",
      to: "/settings?page=integrationLpr",
    },
  },
  {
    id: "rostros",
    category: "Inteligencia artificial",
    question: "¿Reconoce caras?",
    answer: [
      "Sí, hay reconocimiento facial: se activa en Ajustes → Análisis avanzado y se le enseñan las caras en la **Biblioteca de rostros**. Úsalo respetando la privacidad de las personas.",
    ],
    keywords: ["cara", "caras", "rostro", "facial", "reconocimiento"],
    link: {
      label: "Ir a Reconocimiento facial",
      to: "/settings?page=integrationFaceRecognition",
    },
  },
  {
    id: "lento",
    category: "Problemas comunes",
    question: "El sistema está lento o no carga",
    answer: [
      "Espera 1-2 minutos: después de un corte de luz o un cambio de configuración el NVR se reinicia. Si sigue igual, revisa en **Sistema** el uso de memoria y CPU.",
      "Si una cámara nueva coincide con la lentitud, desactívala y avisa al técnico: hay cámaras que necesitan grabarse sin audio.",
    ],
    keywords: [
      "lento",
      "no carga",
      "cuelga",
      "pegado",
      "memoria",
      "cpu",
      "tarda",
    ],
    link: { label: "Ir a Sistema", to: "/system" },
  },
  {
    id: "corte-luz",
    category: "Problemas comunes",
    question: "¿Qué pasa si se corta la luz o Internet?",
    answer: [
      "Al volver la luz, el equipo arranca solo y sigue grabando. Sin Internet **sigue grabando y detectando**: solo se detienen los mosaicos y los avisos, que vuelven solos al recuperar la conexión.",
      "Recomendamos una UPS pequeña para el equipo, el router y las cámaras cableadas.",
    ],
    keywords: ["luz", "corte", "internet", "apagon", "sin conexion", "ups"],
  },
  {
    id: "privacidad",
    category: "Primeros pasos",
    question: "¿Mis videos salen a Internet?",
    answer: [
      "No. Las grabaciones y la IA quedan **dentro del equipo**. Solo salen los mosaicos que configures hacia tu servidor de TV, y los avisos de Telegram (texto).",
    ],
    keywords: [
      "privacidad",
      "nube",
      "internet",
      "seguridad",
      "datos",
      "videos",
    ],
  },
  {
    id: "soporte",
    category: "Problemas comunes",
    question: "No encontré mi respuesta",
    answer: [
      "Escribe a soporte de Orbi360 indicando qué cámara o pantalla tiene el problema y desde cuándo. Si puedes, adjunta una captura de **Ajustes → Red de cámaras** y de **Sistema**.",
    ],
    keywords: ["soporte", "ayuda", "contacto", "tecnico", "problema"],
  },
];

const strip = (text: string) =>
  text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

// Ranks entries by how many words of the query appear in the question,
// keywords or answer (accents and case ignored).
export function searchFaq(
  query: string,
  entries: FaqEntry[] = FAQ,
): FaqEntry[] {
  const words = strip(query)
    .split(/[^a-z0-9_]+/)
    .filter((w) => w.length > 2);
  if (words.length === 0) {
    return entries;
  }
  return entries
    .map((entry) => {
      const question = strip(entry.question);
      const keywords = strip(entry.keywords.join(" "));
      const answer = strip(entry.answer.join(" "));
      const score = words.reduce(
        (total, w) =>
          total +
          (question.includes(w) ? 3 : 0) +
          (keywords.includes(w) ? 2 : 0) +
          (answer.includes(w) ? 1 : 0),
        0,
      );
      return { entry, score };
    })
    .filter(({ score }) => score > 0)
    .sort((a, b) => b.score - a.score)
    .map(({ entry }) => entry);
}
