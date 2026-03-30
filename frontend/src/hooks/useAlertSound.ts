export function useAlertSound() {
  const play = () => {
    try {
      const audio = new Audio('/alert.wav');
      audio.play().catch(() => {
        // Gracefully handle missing audio file or autoplay restrictions
      });
    } catch {
      // Gracefully handle Audio constructor errors
    }
  };
  return { play };
}
