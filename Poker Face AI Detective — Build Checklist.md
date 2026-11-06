# Poker Face: AI Detective — Build Checklist

Nov 6, 2026 · @Muaz

Submit by **November 21**, one day before the November 22, 11:59 PM PST deadline. Win ki guarantee nahi, lekin ye checklist chances barha degi.

Sab se bara focus 3 cheezein hain: live signals screen par saaf dikhen, game 3 minute me complete ho, aur demo video mazedar ho. Competition shuru ho chuki hai, jaise ZenDev aur Glassbreath.

## Nov 5-6: Setup

**Target:** Webcam se live data screen par nazar aaye. Warna baqi kaam rok kar pehle ye fix karo.

- [x] DEV.to par challenge join karo.
- [x] Presage ki API key lo.
- [x] Naya public GitHub repo banao.
- [x] Electron app me SmartSpectra SDK install karo (SDK Node.js aur Electron support karta hai).
- [x] Key `.env` me rakho aur `.env` ko `.gitignore` me daalo.
- [x] Pulse, breathing aur expression screen par live dikhao.
- [x] Agar Claude Code use karte ho, to Presage ki `using-smartspectra` Agent Skill install karo.

## Nov 7-9: Core game

- [x] Ek simple case likho: "Museum se diamond chori hua. Aap suspect ho."
- [x] Game ke steps fix karo: consent, 30-second calm baseline, 6-8 sawal, final verdict.
- [x] Har player ka personal baseline banao.
- [x] Baseline se 10-30 second ka change nikaal kar **Suspicion Meter** chalao.
- [x] Python FastAPI backend banao aur Electron ko WebSocket se connect karo.
- [x] LLM ko signal summary do, taake agla sawal us ke hisaab se badle.
- [x] Pehle text input se poora game test karo.

## Nov 10-13: Voice aur UI

- [ ] Speech-to-text aur AI detective ki voice add karo.
- [ ] Mic fail hone par text input ka fallback rakho.
- [ ] Interrogation room wala dark UI banao.
- [x] Live pulse, breathing, expression aur Suspicion Meter dikhao.
- [x] Har reaction ki wajah dikhao, jaise "Breathing changed after Question 4."
- [x] Kam roshni ya face hatne par warning dikhao.
- [x] Game ke end par timeline dikhao ke kis sawal par kya badla.

## Nov 14-17: Testing

- [ ] Kam az kam 5 logon se unki consent ke saath khelwao.
- [ ] Note karo ke wo kahan confuse hue.
- [ ] Different lighting aur skin tones par test karo.
- [ ] Glasses aur beard ke saath test karo.
- [ ] Crashes, delay aur galat triggers fix karo.
- [ ] Ek naye computer par setup instructions test karo.

## Nov 18-20: Rules aur demo

- [x] Consent screen par batao ke kya data use hota hai.
- [x] App me likho: "Entertainment game. Not a real lie detector or medical tool."
- [ ] Presage ki Telemetry and Privacy page parh kar data handling likho.
- [ ] Disclose karo ke speech ya text kis AI service ko jata hai.
- [ ] README me setup, `.env.example`, architecture aur credits add karo.
- [ ] 60-90 second ki demo video banao, jisme live signals aur game ka reaction saaf dikhe.

## Nov 21: Submit

- [ ] DEV post English me official template se likho.
- [ ] Tags check karo, khaas tor par `#presagechallenge`.
- [ ] Demo, repo link aur consent section add karo.
- [ ] Dono prize categories mention karo.
- [ ] Agar AI coding tool use kiya, to session clean karke embed karo aur **Make Public** karo.
- [ ] Publish karo, phir logged-out browser me post, video aur repo check karo.

**Nov 22:** Sirf emergency fixes ke liye rakho, kyun ke deadline 11:59 PM PST hai.
