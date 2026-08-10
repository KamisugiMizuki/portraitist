type TTSPlayer = {
  init: () => void;
  play: (audioBuffer: ArrayBuffer, onended: () => void | null) => Promise<void>;
  stop: () => void;
};

export function createTTSPlayer(): TTSPlayer {
  let audioContext: any = null;
  let audioBufferSourceNode: any = null;

  const init = () => {
    audioContext = new ((window as any).AudioContext ||
      (window as any).webkitAudioContext)();
    audioContext.suspend();
  };

  const play = async (audioBuffer: ArrayBuffer, onended: () => void | null) => {
    if (audioBufferSourceNode) {
      audioBufferSourceNode.stop();
      audioBufferSourceNode.disconnect();
    }

    const buffer = await audioContext!.decodeAudioData(audioBuffer);
    audioBufferSourceNode = audioContext!.createBufferSource();
    audioBufferSourceNode.buffer = buffer;
    audioBufferSourceNode.connect(audioContext!.destination);
    audioContext!.resume().then(() => {
      audioBufferSourceNode!.start();
    });
    audioBufferSourceNode.onended = onended;
  };

  const stop = () => {
    if (audioBufferSourceNode) {
      audioBufferSourceNode.stop();
      audioBufferSourceNode.disconnect();
      audioBufferSourceNode = null;
    }
    if (audioContext) {
      audioContext.close();
      audioContext = null;
    }
  };

  return { init, play, stop };
}
