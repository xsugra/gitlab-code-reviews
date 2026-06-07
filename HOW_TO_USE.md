# Ako používať Code Review Bot

Tento návod vysvetľuje, ako pripojiť váš GitLab projekt ku Code Review Botu a voliteľne nastaviť notifikácie do Google Chat.

> **Predpoklady:** Bot musí byť už nasadený a bežať. Pozri [SETUP-PRODUCTION.md](SETUP-PRODUCTION.md) pre nastavenie servera.

---

## Krok 1: Pridanie GitLab webhooku na váš projekt

Týmto poviete GitLabu, aby posielal udalosti (push, merge request, atď.) do bota.

1. Otvorte váš GitLab projekt.
![image](images/Screenshot%202026-05-27%20at%2016.44.48.png)

2. Choďte do **Settings > Webhooks**.
![Screenshot 2026-05-27 at 16.45.02.png](images/Screenshot%202026-05-27%20at%2016.45.02.png)

3. Kliknite na **Add new webhook**.
![Screenshot 2026-05-27 at 16.45.27.png](images/Screenshot%202026-05-27%20at%2016.45.27.png)

4. Vyplňte formulár:

| Pole             | Hodnota                                                                        |
|------------------|--------------------------------------------------------------------------------|
| **URL**          | `http://<BOT_IP>:8888/webhook`                                                 |
| **Secret token** | Hodnota `GITLAB_WEBHOOK_SECRET` z `.env` (opýtajte sa administrátora bota)    |

![Screenshot 2026-05-27 at 16.45.56.png](images/Screenshot%202026-05-27%20at%2016.45.56.png)

5. V časti **Trigger** zaškrtnite udalosti, ktoré chcete:

| Trigger                  | Čo bot robí                                                           |
|--------------------------|-----------------------------------------------------------------------|
| **Merge request events** | AI code review + automaticky vyplní prázdny popis MR                 |
| **Push events**          | Kontroluje commity pushnuté priamo do vetvy (mimo MR)                |
| **Pipeline events**      | Analyzuje zlyhané CI/CD pipelines — nájde príčinu, navrhne opravu    |
| **Work item events**     | Automaticky triedí nové issues — priradí labely, závažnosť a súhrn   |
| **Deployment events**    | Analyzuje zlyhané/úspešné deploymenty, postne reporty                |
| **Releases events**      | Generuje release notes z mergnutých MR pri vytvorení releasu         |
| **Tag push events**      | Generuje release notes pri pushnutí nového tagu                      |
| **Emoji events**         | Znovu spustí review, keď pridáte určitú emoji na MR                  |

> **Tip:** Môžete zapnúť všetky. Bot spracuje len relevantné udalosti a zvyšok ignoruje.

![Screenshot 2026-05-27 at 16.46.53.png](images/Screenshot%202026-05-27%20at%2016.46.53.png)

6. Odškrtnite **Enable SSL verification** (pokiaľ nemáte HTTPS na bot-ovi).
7. Kliknite **Add webhook**.
![Screenshot 2026-05-27 at 19.52.43.png](images/Screenshot%202026-05-27%20at%2019.52.43.png)

### Overenie, že to funguje

Po uložení kliknite na tlačidlo **Test** vedľa vášho webhooku a vyberte **Push events**. Mali by ste vidieť zelenú odpoveď `200 OK`.

Alternatívne vytvorte testovací merge request — bot by mal pridať komentáre s code review do pár minút.

---

## Krok 2: Zistenie Project ID

Project ID potrebujete na nastavenie Google Chat notifikácií. Nájdete ho dvoma spôsobmi:

- **Settings > General** — Project ID je zobrazený na vrchu stránky.
- **Hlavná stránka projektu** — zobrazuje sa pod názvom projektu (napr. `Project ID: 34`).

![Screenshot 2026-05-27 at 19.52.43.png](images/Screenshot%202026-05-27%20at%2019.52.43.png)

Zapamätajte si toto číslo pre Krok 4.

---

## Krok 3: Vytvorenie Google Chat Space webhooku

Toto umožní botu posielať notifikácie o review do Google Chat priestoru.

1. Otvorte **Google Chat** (chat.google.com).
2. Otvorte priestor (space), kde chcete dostávať notifikácie.
![Screenshot 2026-05-27 at 16.51.02.png](images/Screenshot%202026-05-27%20at%2016.51.02.png)
3. Kliknite na **názov priestoru** hore pre otvorenie nastavení.
4. Choďte do **Manage apps & integrations** (alebo **Manage webhooks** v starších verziách).
![Screenshot 2026-05-27 at 16.51.35.png](images/Screenshot%202026-05-27%20at%2016.51.35.png)
5. Kliknite na **Add webhooks**.
![Screenshot 2026-05-27 at 16.51.53.png](images/Screenshot%202026-05-27%20at%2016.51.53.png)
6. Zadajte názov, napr. `Code Review Bot`.
7. Voliteľne nastavte URL avatara.
8. Kliknite **Save**.
9. **Skopírujte webhook URL** — vyzerá takto:
   ```
   https://chat.googleapis.com/v1/spaces/XXXXX/messages?key=...&token=...
   ```

> **Dôležité:** Tento URL obsahuje prístupové údaje. Nezdieľajte ho verejne.

---

## Krok 4: Prepojenie Google Chat s vaším projektom (Admin UI)

Teraz prepojte Google Chat webhook s vaším GitLab projektom v admin paneli bota.

1. Otvorte admin rozhranie bota: `http://<BOT_IP>:port/code-review-bot/`
![Screenshot 2026-05-27 at 16.47.48.png](images/Screenshot%202026-05-27%20at%2016.47.48.png)
2. Prihláste sa administrátorským heslom (`ADMIN_PASSWORD`).
3. Choďte na **Webhooks** v navigácii.
4. Kliknite na **Add New Webhook**.
![Screenshot 2026-05-27 at 16.48.01.png](images/Screenshot%202026-05-27%20at%2016.48.01.png)
5. Vyplňte formulár:

| Pole                        | Hodnota                                                   |
|-----------------------------|-----------------------------------------------------------|
| **Project ID**              | GitLab Project ID z Kroku 2 (napr. `34`)                 |
| **Project Name**            | Voliteľne — zobrazovací názov (napr. `web/moj-projekt`)  |
| **Google Chat Webhook URL** | URL, ktorý ste skopírovali v Kroku 3                      |
| **Enabled**                 | Zaškrtnite pre aktiváciu notifikácií                      |

![Screenshot 2026-05-27 at 16.48.19.png](images/Screenshot%202026-05-27%20at%2016.48.19.png)

6. Kliknite **Create**.
7. Kliknite **Test** pre overenie — v Google Chat priestore by sa mala zobraziť testovacia správa.

> **Poznámka:** Projekty bez Google Chat webhooku stále dostanú review ako GitLab komentáre. Chat notifikácia je voliteľná.

---

## Ako to funguje

Po nakonfigurovaní bot spracováva udalosti automaticky:

```
GitLab udalosť (push, MR, atď.)
    │
    ▼
Bot prijme webhook ──→ Stiahne kontext z GitLab API
    │
    ▼
LLM analyzuje kód (Ollama, beží lokálne)
    │
    ├──→ Postne zistenia ako GitLab komentáre (vždy)
    ├──→ Pošle Google Chat notifikáciu (ak je nastavená)
    └──→ Uloží do databázy (história review)
```

---

## Prehľad udalostí

### Merge Request Review

- **Spúšťa sa pri:** MR otvorený, znovuotvorený alebo aktualizovaný s novými commitmi.
- **Čo robí:** AI skontroluje diff a postne detailný komentár na MR.
- **Auto-popis:** Ak je popis MR prázdny, bot ho automaticky vygeneruje z diffu.

### Push Review

- **Spúšťa sa pri:** Commity pushnuté priamo do vetvy (mimo MR).
- **Čo robí:** Skontroluje pushnuté commity a postne komentár na posledný commit.

### Analýza zlyhania Pipeline

- **Spúšťa sa pri:** CI/CD pipeline zlyhala.
- **Čo robí:** Stiahne logy zlyhého jobu, nájde príčinu a navrhne opravu.
- **Poznámka:** Úspešné pipelines sú ignorované — analyzujú sa len zlyhania.

### Triaž Issues

- **Spúšťa sa pri:** Vytvorený nový issue.
- **Čo robí:** Klasifikuje issue, navrhne labely a závažnosť, postne súhrnný komentár.

### Analýza Deploymentu

- **Spúšťa sa pri:** Deployment uspel alebo zlyhal.
- **Čo robí:** Analyzuje deployment a postne report na súvisiacom commite.

### Release Notes

- **Spúšťa sa pri:** Vytvorený release alebo pushnutý nový tag.
- **Čo robí:** Zozbiera mergnuté MR od posledného releasu a vygeneruje changelog.

### Emoji Re-trigger

- **Spúšťa sa pri:** Niekto pridá nakonfigurovanú emoji (predvolene: `:repeat:`) na MR.
- **Čo robí:** Znovu spustí code review na danom MR.
- **Nastavenie:** Uistite sa, že **Emoji events** je zapnutý vo vašich GitLab webhook triggeroch.
- **Použitie:** Otvorte MR, kliknite na výber emoji a pridajte `:repeat:` emoji.

---

## Správa webhookov

V admin rozhraní (`/code-review-bot/webhooks`) môžete:

| Akcia      | Popis                                                      |
|------------|------------------------------------------------------------|
| **Create** | Pridať nový projekt s Google Chat webhook URL              |
| **Edit**   | Zmeniť webhook URL alebo názov projektu                    |
| **Toggle** | Zapnúť/vypnúť notifikácie bez vymazania konfigurácie       |
| **Test**   | Poslať testovaciu správu pre overenie Google Chat spojenia |
| **Delete** | Úplne odstrániť konfiguráciu webhooku                      |

---

## Riešenie problémov

### Bot nereaguje na môj merge request

1. Skontrolujte, či je GitLab webhook správne nakonfigurovaný:
   - Choďte do **Project > Settings > Webhooks > Edit > Recent deliveries**.
   - Hľadajte odpoveď `200 OK`.
2. Ak vidíte `401`, secret token sa nezhoduje.
3. Ak vidíte chybu spojenia, bot je nedostupný — skontrolujte URL a firewall.

### Review je na GitLabe, ale nie v Google Chate

1. Otvorte admin rozhranie a skontrolujte, či je webhook nakonfigurovaný pre váš Project ID.
2. Uistite sa, že webhook je **Enabled** (zelený stav).
3. Kliknite **Test** — ak zlyháva, Google Chat webhook URL mohol exspirovať. Vytvorte nový v Google Chat a aktualizujte ho.

### Bot ignoruje moje push eventy

- Uistite sa, že **Push events** je zapnutý v GitLab webhook triggeroch.
- Bot kontroluje len pushy, ktoré obsahujú commity — prázdne pushy (napr. zmazanie vetvy) sú ignorované.

### Bot ignoruje pipeline eventy

- Uistite sa, že **Pipeline events** je zapnutý v GitLab webhook triggeroch.
- Bot analyzuje len **zlyhané** pipelines. Úspešné pipelines sú zámerne ignorované.

### Chcem znovu spustiť review

Pridajte `:repeat:` emoji na MR. Uistite sa, že **Emoji events** je zapnutý v GitLab webhook triggeroch.

### Veľký MR trvá príliš dlho / vyprší čas

LLM potrebuje čas na veľké diffy. Môžete:
- Zvýšiť `OLLAMA_TIMEOUT_S` v `.env` (predvolene: 1800 sekúnd = 30 minút).
- Použiť menší/rýchlejší model (zmeniť `OLLAMA_MODEL` v `.env`).
- Znížiť `MAX_CHUNK_CHARS` pre posielanie menších častí do LLM.
