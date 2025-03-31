// speech.js - Enhanced with command history, confidence scoring, and multi-language support

class SpeechSystem {
  static languages = {
    english: { code: 'en-US', name: 'English' },
    spanish: { code: 'es-ES', name: 'Spanish' },
    french: { code: 'fr-FR', name: 'French' }
  };

  constructor() {
    this.synth = window.speechSynthesis;
    this.queue = [];
    this.speaking = false;
    this.muted = false;
    this.pitch = 1;
    this.rate = 1;
    this.voicePref = 'female';
    this.quiet = false;
    this.language = 'english';
    this.commandHistory = [];
    this.minConfidence = 0.7;
    this.recognition = null;
    this.wakeRecognizer = null;
    this.wakeWordEnabled = true;
    this.wakeListening = false;
    this.lastSpokenMessage = "";
    this.lastSpokenTime = 0;
  }

  async init() {
    await this.loadVoices();
    this.setupRecognition();
    this.setupWakeWord();
    this.populateVoiceSelector();
    this.populateLanguageSelector();
  }

  async loadVoices() {
    return new Promise((resolve) => {
      const voices = this.synth.getVoices();
      if (voices.length > 0) {
        this.voices = voices;
        resolve();
      } else {
        this.synth.onvoiceschanged = () => {
          this.voices = this.synth.getVoices();
          resolve();
        };
      }
    });
  }

  setupRecognition() {
    this.recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
    this.recognition.continuous = false;
    this.recognition.interimResults = false;
    this.recognition.maxAlternatives = 3;
    this.recognition.lang = this.languages[this.language].code;

    this.recognition.onresult = (event) => {
      const alternatives = Array.from(event.results[0])
        .map(alt => ({
          text: alt.transcript,
          confidence: alt.confidence
        }))
        .sort((a, b) => b.confidence - a.confidence);

      this.commandHistory.push({
        timestamp: Date.now(),
        alternatives,
        executed: false
      });

      const bestMatch = alternatives[0];
      if (bestMatch.confidence >= this.minConfidence) {
        this.processVoiceCommand(bestMatch.text);
        this.commandHistory[this.commandHistory.length - 1].executed = true;
      } else {
        this.speak("Sorry, I didn't catch that clearly. Please repeat.");
      }
    };

    this.recognition.onerror = (event) => {
      console.error("Speech recognition error:", event.error);
      this.speak("Sorry, I didn't catch that.");
    };
  }

  setupWakeWord() {
    this.wakeRecognizer = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
    this.wakeRecognizer.continuous = true;
    this.wakeRecognizer.interimResults = false;
    this.wakeRecognizer.lang = this.languages[this.language].code;

    this.wakeRecognizer.onresult = (event) => {
      const transcript = event.results[event.results.length - 1][0].transcript.toLowerCase();
      if (this.wakeWordEnabled && (transcript.includes("hat") || transcript.includes("smart hat"))) {
        this.speak("Yes? I'm listening...");
        this.startListening();
      }
    };

    this.wakeRecognizer.onerror = (event) => {
      console.error("Wake word recognizer error:", event.error);
    };
  }

  startWakeWordListener() {
    if (this.wakeWordEnabled && !this.wakeListening) {
      this.wakeRecognizer.start();
      this.wakeListening = true;
    }
  }

  startListening() {
    if (this.recognition) {
      this.speak("Listening...");
      this.recognition.start();
    }
  }

  speak(msg, options = {}) {
    if (this.muted || this.quiet || !msg) return;

    const now = Date.now();
    if (msg === this.lastSpokenMessage && now - this.lastSpokenTime < 1000) {
      console.log("[Speech] Duplicate message skipped");
      return;
    }

    this.lastSpokenMessage = msg;
    this.lastSpokenTime = now;

    const utter = new SpeechSynthesisUtterance(msg);
    utter.pitch = options.pitch || this.pitch;
    utter.rate = options.rate || this.rate;
    utter.voice = this.getVoice();
    utter.lang = this.languages[this.language].code;

    utter.onend = () => {
      this.speaking = false;
      this.processQueue();
    };

    this.queue.push(utter);
    this.processQueue();
  }

  processQueue() {
    if (this.speaking || this.queue.length === 0) return;
    this.speaking = true;
    const next = this.queue.shift();
    this.synth.speak(next);
  }

  getVoice() {
    const selected = document.getElementById('voiceSelector')?.value || this.voicePref;
    const voiceMatch = this.voices.find(v => 
      selected === 'female' 
        ? /(female|woman|samantha|zira)/i.test(v.name)
        : /(male|man|david|daniel)/i.test(v.name));
    
    return voiceMatch || this.voices[0];
  }

  mute(toggle) {
    this.muted = toggle;
    if (toggle) {
      this.synth.cancel();
      this.queue = [];
    }
  }

  populateVoiceSelector() {
    const selector = document.getElementById('voiceSelector');
    if (!selector) return;

    selector.innerHTML = `
      <option value="female">Female</option>
      <option value="male">Male</option>
    `;

    selector.addEventListener('change', () => {
      this.voicePref = selector.value;
      this.speak(`Voice changed to ${selector.value}`);
    });
  }

  populateLanguageSelector() {
    const selector = document.getElementById('languageSelector');
    if (!selector) return;

    selector.innerHTML = Object.entries(this.languages)
      .map(([key, lang]) => `<option value="${key}">${lang.name}</option>`)
      .join('');

    selector.addEventListener('change', () => {
      this.language = selector.value;
      this.recognition.lang = this.languages[this.language].code;
      this.wakeRecognizer.lang = this.languages[this.language].code;
      this.speak(`Language set to ${this.languages[this.language].name}`);
    });
  }

  toggleWakeWord(enabled) {
    this.wakeWordEnabled = enabled;
    if (enabled && !this.wakeListening) {
      this.wakeRecognizer.start();
      this.wakeListening = true;
    } else if (!enabled && this.wakeListening) {
      this.wakeRecognizer.stop();
      this.wakeListening = false;
    }
  }

  updateCommandHistoryUI() {
    const historyList = document.getElementById('commandHistory');
    if (!historyList) return;

    historyList.innerHTML = this.commandHistory
      .slice(-5)
      .reverse()
      .map(cmd => `
        <li class="${cmd.executed ? 'executed' : 'rejected'}">
          ${new Date(cmd.timestamp).toLocaleTimeString()}: 
          ${cmd.alternatives[0].text} (${Math.round(cmd.alternatives[0].confidence * 100)}%)
        </li>
      `)
      .join('');
  }
}

// Initialize singleton instance
const Speech = new SpeechSystem();

// Global helper functions
function speak(msg, options) {
  Speech.speak(msg, options);
}

function toggleMute() {
  const toggle = document.getElementById('muteToggle');
  Speech.mute(toggle.checked);
}

function startListening() {
  Speech.startListening();
}

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  Speech.init();
  Speech.startWakeWordListener();
});
