const MUSIC_STEP_SECONDS = 0.36;
const MUSIC_NOTES = [146.83, 174.61, 220, 174.61, 164.81, 196, 246.94, 196];

/** Lightweight procedural game audio. No audio files are downloaded or bundled. */
export class Soundscape {
  private context: AudioContext | null = null;
  private musicGain: GainNode | null = null;
  private musicTimer: number | null = null;
  private musicStep = 0;
  private musicEnabled = localStorage.getItem("dropfire-music") !== "off";

  unlock(): void {
    const context = this.getContext();
    if (!context) return;
    void context.resume();
    if (this.musicEnabled) this.startMusic();
  }

  toggleMusic(): boolean {
    this.musicEnabled = !this.musicEnabled;
    localStorage.setItem("dropfire-music", this.musicEnabled ? "on" : "off");
    if (this.musicEnabled) {
      this.unlock();
    } else {
      this.stopMusic();
    }
    return this.musicEnabled;
  }

  isMusicEnabled(): boolean {
    return this.musicEnabled;
  }

  playShot(weapon: "pistol" | "rifle"): void {
    const context = this.getContext();
    if (!context || context.state !== "running") return;

    const now = context.currentTime;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = weapon === "rifle" ? "sawtooth" : "square";
    oscillator.frequency.setValueAtTime(weapon === "rifle" ? 165 : 240, now);
    oscillator.frequency.exponentialRampToValueAtTime(55, now + (weapon === "rifle" ? 0.12 : 0.08));
    gain.gain.setValueAtTime(0.035, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + (weapon === "rifle" ? 0.14 : 0.1));
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(now);
    oscillator.stop(now + (weapon === "rifle" ? 0.14 : 0.1));
  }

  playEmptyClick(): void {
    const context = this.getContext();
    if (!context || context.state !== "running") return;

    const now = context.currentTime;
    for (const delay of [0, 0.04]) {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = "square";
      oscillator.frequency.setValueAtTime(180, now + delay);
      gain.gain.setValueAtTime(0.02, now + delay);
      gain.gain.exponentialRampToValueAtTime(0.001, now + delay + 0.03);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(now + delay);
      oscillator.stop(now + delay + 0.03);
    }
  }

  playHitMarker(): void {
    const context = this.getContext();
    if (!context || context.state !== "running") return;

    const now = context.currentTime;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "square";
    oscillator.frequency.setValueAtTime(880, now);
    oscillator.frequency.exponentialRampToValueAtTime(440, now + 0.05);
    gain.gain.setValueAtTime(0.025, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.06);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(now);
    oscillator.stop(now + 0.06);
  }

  playHurt(): void {
    const context = this.getContext();
    if (!context || context.state !== "running") return;

    const now = context.currentTime;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sawtooth";
    oscillator.frequency.setValueAtTime(160, now);
    oscillator.frequency.exponentialRampToValueAtTime(50, now + 0.12);
    gain.gain.setValueAtTime(0.05, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.14);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(now);
    oscillator.stop(now + 0.14);
  }

  playBlock(): void {
    const context = this.getContext();
    if (!context || context.state !== "running") return;

    const now = context.currentTime;
    for (const [offset, frequency] of [[0, 1400], [0.03, 2100]] as const) {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = "triangle";
      oscillator.frequency.setValueAtTime(frequency, now + offset);
      gain.gain.setValueAtTime(0.02, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.001, now + offset + 0.08);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(now + offset);
      oscillator.stop(now + offset + 0.08);
    }
  }

  playHeal(): void {
    const context = this.getContext();
    if (!context || context.state !== "running") return;

    const now = context.currentTime;
    for (const [offset, frequency] of [[0, 523.25], [0.07, 783.99]] as const) {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(frequency, now + offset);
      gain.gain.setValueAtTime(0.03, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.001, now + offset + 0.16);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(now + offset);
      oscillator.stop(now + offset + 0.16);
    }
  }

  private getContext(): AudioContext | null {
    if (this.context) return this.context;
    const AudioContextConstructor = window.AudioContext
      ?? (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextConstructor) return null;
    this.context = new AudioContextConstructor();
    return this.context;
  }

  private startMusic(): void {
    const context = this.context;
    if (!context || this.musicTimer !== null) return;
    this.musicGain = context.createGain();
    this.musicGain.gain.value = 0.024;
    this.musicGain.connect(context.destination);
    this.playMusicStep();
    this.musicTimer = window.setInterval(() => this.playMusicStep(), MUSIC_STEP_SECONDS * 1000);
  }

  private stopMusic(): void {
    if (this.musicTimer !== null) window.clearInterval(this.musicTimer);
    this.musicTimer = null;
    this.musicGain?.disconnect();
    this.musicGain = null;
  }

  private playMusicStep(): void {
    const context = this.context;
    const output = this.musicGain;
    if (!context || !output || context.state !== "running") return;
    const now = context.currentTime;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = MUSIC_NOTES[this.musicStep % MUSIC_NOTES.length];
    gain.gain.setValueAtTime(0.001, now);
    gain.gain.exponentialRampToValueAtTime(0.7, now + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.001, now + MUSIC_STEP_SECONDS * 0.85);
    oscillator.connect(gain).connect(output);
    oscillator.start(now);
    oscillator.stop(now + MUSIC_STEP_SECONDS);
    this.musicStep += 1;
  }
}

export const soundscape = new Soundscape();
