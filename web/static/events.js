export function connectEvents(onEvent) {
  const source = new EventSource("/events");
  source.onmessage = (message) => onEvent(JSON.parse(message.data));
  // EventSource reconnects on its own; this exists so a failure is visible
  // rather than silent.
  source.onerror = () => console.warn("event stream dropped, retrying");
  return source;
}
