// Tiny translation table — keyed off config.language (es | en | pt).
// English mirrors the legacy strings; Spanish + Portuguese match the existing
// UI tone in the legacy app (Spanish was the deployed copy).

export type Lang = "es" | "en" | "pt" | string

type Dict = {
  assistant: string
  newConversation: string
  groupToday: string
  groupYesterday: string
  groupOlder: string
  noConversations: string
  online: string
  offline: string
  modeLabelTheme: string
  modeLabelMode: string
  themeLight: string
  themeDark: string
  themeAuto: string
  modeChat: string
  modeVoice: string
  modeVision: string
  greetingPrefix: string
  startSubtitle: string
  inputPlaceholder: string
  voiceModeHint: string
  visionModeHint: string
  settings: string
  language: string
  knownPeople: string
  knownPeopleHint: string
  enroll: string
  uploading: string
  removePerson: (n: string) => string
  removed: (n: string) => string
  registered: (n: string) => string
  delete: string
  cancel: string
  deleteConversationTitle: string
  deleteConversationBody: (title: string) => string
  enterName: string
  selectPhoto: string
  logout: string
  closeMenu: string
  settingsAria: string
  micMute: string
  micUnmute: string
  micProcessing: string
  attachFile: string
  removeAttachment: string
  attachmentTooLarge: (name: string) => string
  attachmentTypeUnsupported: (name: string) => string
  attachmentReadFailed: (name: string) => string
  attachmentLimitReached: string
}

const ES: Dict = {
  assistant: "asistente",
  newConversation: "Nueva conversación",
  groupToday: "Hoy",
  groupYesterday: "Ayer",
  groupOlder: "Anteriores",
  noConversations: "Aún no hay conversaciones.",
  online: "En línea",
  offline: "Sin conexión",
  modeLabelTheme: "Tema",
  modeLabelMode: "Modo",
  themeLight: "Claro",
  themeDark: "Oscuro",
  themeAuto: "Auto",
  modeChat: "Chat",
  modeVoice: "Voz",
  modeVision: "Visión",
  greetingPrefix: "Hola, soy",
  startSubtitle:
    "Escribe tu mensaje o activa el modo Realtime para hablar.",
  inputPlaceholder: "Escribe tu mensaje…",
  voiceModeHint: "Modo voz — habla con naturalidad",
  visionModeHint: "Voz + visión — la cámara está activa",
  settings: "Ajustes",
  language: "Idioma",
  knownPeople: "Personas conocidas",
  knownPeopleHint:
    "Las caras registradas aquí se reconocen en modo visión. El modelo las saluda por nombre cuando aparecen en el cuadro.",
  enroll: "Registrar",
  uploading: "Subiendo…",
  removePerson: (n) => `¿Quitar a ${n} de las personas conocidas?`,
  removed: (n) => `${n} eliminado`,
  registered: (n) => `${n} registrado`,
  delete: "Eliminar",
  cancel: "Cancelar",
  deleteConversationTitle: "¿Eliminar conversación?",
  deleteConversationBody: (t) =>
    `"${t}" se borrará permanentemente junto con sus mensajes.`,
  enterName: "Escribe un nombre primero",
  selectPhoto: "Selecciona una foto",
  logout: "Cerrar sesión",
  closeMenu: "Cerrar menú",
  settingsAria: "Ajustes",
  micMute: "Silenciar micrófono",
  micUnmute: "Activar micrófono",
  micProcessing: "Procesando — clic para forzar mic on",
  attachFile: "Adjuntar archivo",
  removeAttachment: "Quitar adjunto",
  attachmentTooLarge: (n) => `${n} supera el tamaño máximo (1 MB).`,
  attachmentTypeUnsupported: (n) => `${n}: formato no soportado en esta versión.`,
  attachmentReadFailed: (n) => `No se pudo leer ${n}.`,
  attachmentLimitReached: "Máximo 5 archivos por mensaje.",
}

const EN: Dict = {
  assistant: "assistant",
  newConversation: "New conversation",
  groupToday: "Today",
  groupYesterday: "Yesterday",
  groupOlder: "Older",
  noConversations: "No conversations yet.",
  online: "Online",
  offline: "Offline",
  modeLabelTheme: "Theme",
  modeLabelMode: "Mode",
  themeLight: "Light",
  themeDark: "Dark",
  themeAuto: "Auto",
  modeChat: "Chat",
  modeVoice: "Voice",
  modeVision: "Vision",
  greetingPrefix: "Hi, I'm",
  startSubtitle:
    "Type your message, or switch to Realtime mode to talk.",
  inputPlaceholder: "Type your message…",
  voiceModeHint: "Voice — speak naturally",
  visionModeHint: "Vision + voice — camera is live",
  settings: "Settings",
  language: "Language",
  knownPeople: "Known people",
  knownPeopleHint:
    "Faces enrolled here are recognized in vision mode. The model greets them by name when they enter the frame.",
  enroll: "Enroll",
  uploading: "Uploading…",
  removePerson: (n) => `Remove ${n} from known people?`,
  removed: (n) => `${n} removed`,
  registered: (n) => `${n} registered`,
  delete: "Delete",
  cancel: "Cancel",
  deleteConversationTitle: "Delete conversation?",
  deleteConversationBody: (t) =>
    `"${t}" will be permanently deleted along with its messages.`,
  enterName: "Enter a name first",
  selectPhoto: "Select a photo",
  logout: "Log out",
  closeMenu: "Close menu",
  settingsAria: "Settings",
  micMute: "Mute microphone",
  micUnmute: "Unmute microphone",
  micProcessing: "Processing — click to force mic on",
  attachFile: "Attach file",
  removeAttachment: "Remove attachment",
  attachmentTooLarge: (n) => `${n} exceeds the size limit (1 MB).`,
  attachmentTypeUnsupported: (n) => `${n}: unsupported format in this release.`,
  attachmentReadFailed: (n) => `Couldn't read ${n}.`,
  attachmentLimitReached: "Maximum 5 files per message.",
}

const PT: Dict = {
  ...EN,
  assistant: "assistente",
  newConversation: "Nova conversa",
  groupToday: "Hoje",
  groupYesterday: "Ontem",
  groupOlder: "Anteriores",
  noConversations: "Nenhuma conversa ainda.",
  online: "Online",
  offline: "Sem conexão",
  modeLabelTheme: "Tema",
  modeLabelMode: "Modo",
  themeLight: "Claro",
  themeDark: "Escuro",
  themeAuto: "Auto",
  modeChat: "Chat",
  modeVoice: "Voz",
  modeVision: "Visão",
  greetingPrefix: "Olá, sou",
  startSubtitle: "Escreva sua mensagem, ou ative o modo Realtime para falar.",
  inputPlaceholder: "Escreva sua mensagem…",
  voiceModeHint: "Voz — fale naturalmente",
  visionModeHint: "Voz + visão — a câmera está ativa",
  settings: "Ajustes",
  language: "Idioma",
}

const DICTS: Record<string, Dict> = { es: ES, en: EN, pt: PT }

export function t(lang: Lang | undefined): Dict {
  if (!lang) return EN
  return DICTS[lang] ?? EN
}
