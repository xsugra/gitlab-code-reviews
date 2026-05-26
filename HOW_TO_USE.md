# Ako pouzivat Code Review Bot

Tento navod vysvetluje, ako pripojit vas GitLab projekt ku Code Review Botu a volitelne nastavit notifikacie do Google Chat.

> **Predpoklady:** Bot musi byt uz nasadeny a bezat. Pozri [SETUP-PRODUCTION.md](SETUP-PRODUCTION.md) pre nastavenie servera.

---

## Krok 1: Pridanie GitLab webhooku na vas projekt

Tymto poviete GitLabu, aby posielal udalosti (pushy, merge requesty, atd.) do bota.

1. Otvorte vas GitLab projekt.
2. Chodte do **Settings > Webhooks**.
3. Kliknite na **Add new webhook**.
4. Vyplnte formular:

| Pole            | Hodnota                                         |
|-----------------|-------------------------------------------------|
| **URL**         | `http://<BOT_IP>:8888/webhook`                  |
| **Secret token**| Hodnota `GITLAB_WEBHOOK_SECRET` z `.env` (opytajte sa administratora bota) |

5. V casti **Trigger** zapiajte udalosti, ktore chcete:

| Trigger                  | Co bot robi                                                      |
|--------------------------|------------------------------------------------------------------|
| **Merge request events** | AI code review + automaticky vyplni prazdny popis MR             |
| **Push events**          | Kontroluje commity pushnute priamo do vetvy (mimo MR)            |
| **Pipeline events**      | Analyzuje zlyhanue CI/CD pipelines — najde pricinu, navrhne opravu |
| **Work item events**     | Automaticky triedi nove issues — priradi labely, zavaznost a sumar |
| **Deployment events**    | Analyzuje zlyhane/uspesne deploymenty, postne reporty            |
| **Releases events**      | Generuje release notes z mergenutych MR pri vytvoreni releasu    |
| **Tag push events**      | Generuje release notes pri pushnuti noveho tagu                  |
| **Emoji events**         | Znovu spusti review ked pridate urcitu emoji na MR               |

> **Tip:** Mozete zapnut vsetky. Bot spracuje len relevantne udalosti a zvysok ignoruje.

6. Odskrtnite **Enable SSL verification** (pokial nemate HTTPS na bote).
7. Kliknite **Add webhook**.

### Overenie ze to funguje

Po ulozeni kliknite na tlacidlo **Test** vedla vasho webhooku a vyberte **Push events**. Mali by ste vidiet zelenu odpoved `200 OK`.

Alternativne vytvorte testovaci merge request — bot by mal pridat komentare s code review do par minut.

---

## Krok 2: Zistenie Project ID

Project ID potrebujete na nastavenie Google Chat notifikacii. Najdete ho dvoma sposobmi:

- **Settings > General** — Project ID je zobrazeny na vrchu stranky.
- **Hlavna stranka projektu** — zobrazuje sa pod nazvom projektu (napr. `Project ID: 34`).

Zapamatajte si toto cislo pre Krok 4.

---

## Krok 3: Vytvorenie Google Chat Space webhooku

Toto umozni botu posielat notifikacie o review do Google Chat priestoru.

1. Otvorte **Google Chat** (chat.google.com).
2. Otvorte priestor (space), kde chcete dostavat notifikacie.
3. Kliknite na **nazov priestoru** hore pre otvorenie nastaveni.
4. Chodte do **Manage apps & integrations** (alebo **Manage webhooks** v starsich verziach).
5. Kliknite na **Add webhooks**.
6. Zadajte nazov, napr. `Code Review Bot`.
7. Volitelne nastavte URL avatara.
8. Kliknite **Save**.
9. **Skopirajte webhook URL** — vyzera takto:
   ```
   https://chat.googleapis.com/v1/spaces/XXXXX/messages?key=...&token=...
   ```

> **Dolezite:** Tento URL obsahuje pristupove udaje. Nezdielajte ho verejne.

---

## Krok 4: Prepojenie Google Chat s vasim projektom (Admin UI)

Teraz prepojte Google Chat webhook s vasim GitLab projektom v admin paneli bota.

1. Otvorte admin rozhranie bota: `http://<BOT_IP>:8888/code-review-bot/`
2. Prihlaste sa vasim GitLab uctom (OAuth).
3. Chodte na **Webhooks** v navigacii.
4. Kliknite na **Add New Webhook**.
5. Vyplnte formular:

| Pole                         | Hodnota                                                   |
|------------------------------|-----------------------------------------------------------|
| **Project ID**               | GitLab Project ID z Kroku 2 (napr. `34`)                 |
| **Project Name**             | Volitelne — zobrazovaci nazov (napr. `web/moj-projekt`)  |
| **Google Chat Webhook URL**  | URL, ktory ste skopirovali v Kroku 3                      |
| **Enabled**                  | Zaskrtnite pre aktivaciu notifikacii                      |

6. Kliknite **Create**.
7. Kliknite **Test** pre overenie — v Google Chat priestore by sa mala zobrazit testovacia sprava.

> **Poznamka:** Projekty bez Google Chat webhooku stale dostanu review ako GitLab komentare. Chat notifikacia je volitelna.

---

## Ako to funguje

Po nakonfigurovani bot spracovava udalosti automaticky:

```
GitLab udalost (push, MR, atd.)
    |
    v
Bot prijme webhook ---> Stiahne kontext z GitLab API
    |
    v
LLM analyzuje kod (Ollama, bezi lokalne)
    |
    |---> Postne zistenia ako GitLab komentare (vzdy)
    |---> Posle Google Chat notifikaciu (ak je nastavena)
    '---> Ulozi do databazy (historia review)
```

---

## Prehlad udalosti

### Merge Request Review

- **Spusta sa pri:** MR otvoreny, znovuotvoreny alebo aktualizovany s novymi commitmi.
- **Co robi:** AI skontroluje diff a postne detailny koment na MR.
- **Auto-popis:** Ak je popis MR prazdny, bot ho automaticky vygeneruje z diffu.

### Push Review

- **Spusta sa pri:** Commity pushnute priamo do vetvy (mimo MR).
- **Co robi:** Skontroluje pushnute commity a postne koment na posledny commit.

### Analyza zlyhania Pipeline

- **Spusta sa pri:** CI/CD pipeline zlyhala.
- **Co robi:** Stiahne logy zlyhaneho jobu, najde pricinu a navrhne opravu.
- **Poznamka:** Uspesne pipelines su ignorovane — analyzuju sa len zlyhania.

### Triaz Issues

- **Spusta sa pri:** Vytvoreny novy issue.
- **Co robi:** Klasifikuje issue, navrhne labely a zavaznost, postne sumarny koment.

### Analyza Deploymentu

- **Spusta sa pri:** Deployment uspel alebo zlyhal.
- **Co robi:** Analyzuje deployment a postne report na suvisiacom commite.

### Release Notes

- **Spusta sa pri:** Vytvoreny release alebo pushnuty novy tag.
- **Co robi:** Zozbiera mergnute MR od posledneho releasu a vygeneruje changelog.

### Emoji Re-trigger

- **Spusta sa pri:** Niekto prida nakonfigurovanu emoji (predvolene: :repeat: ) na MR.
- **Co robi:** Znovu spusti code review na danom MR.
- **Nastavenie:** Uistite sa, ze **Emoji events** je zapnuty vo vasich GitLab webhook triggeroch.
- **Pouzitie:** Otvorte MR, kliknite na vyber emoji a pridajte :repeat: emoji.

---

## Sprava webhookov

V admin rozhrani (`/code-review-bot/webhooks`) mozete:

| Akcia          | Popis                                                    |
|----------------|----------------------------------------------------------|
| **Create**     | Pridat novy projekt s Google Chat webhook URL             |
| **Edit**       | Zmenit webhook URL alebo nazov projektu                   |
| **Toggle**     | Zapnut/vypnut notifikacie bez vymazania konfiguracie      |
| **Test**       | Poslat testovaciu spravu pre overenie Google Chat spojenia |
| **Delete**     | Uplne odstranit konfiguraciu webhooku                     |

---

## Riesenie problemov

### Bot nereaguje na moj merge request

1. Skontrolujte ci je GitLab webhook spravne nakonfigurovany:
   - Chodte do **Project > Settings > Webhooks > Edit > Recent deliveries**.
   - Hladajte odpoved `200 OK`.
2. Ak vidite `401`, secret token sa nezhoduje.
3. Ak vidite chybu spojenia, bot je nedostupny — skontrolujte URL a firewall.

### Review je na GitLabe, ale nie v Google Chate

1. Otvorte admin rozhranie a skontrolujte, ci je webhook nakonfigurovany pre vas Project ID.
2. Uistite sa, ze webhook je **Enabled** (zeleny stav).
3. Kliknite **Test** — ak zlyhava, Google Chat webhook URL mohol exspirovat. Vytvorte novy v Google Chat a aktualizujte ho.

### Bot ignoruje moje push eventy

- Uistite sa, ze **Push events** je zapnuty v GitLab webhook triggeroch.
- Bot kontroluje len pushy, ktore obsahuju commity — prazdne pushy (napr. zmazanie vetvy) su ignorovane.

### Bot ignoruje pipeline eventy

- Uistite sa, ze **Pipeline events** je zapnuty v GitLab webhook triggeroch.
- Bot analyzuje len **zlyhane** pipelines. Uspesne pipelines su zamerne ignorovane.

### Chcem znovu spustit review

Pridajte :repeat: emoji na MR. Uistite sa, ze **Emoji events** je zapnuty v GitLab webhook triggeroch.

### Velky MR trva prilis dlho / vyprsi cas

LLM potrebuje cas na velke diffy. Mozete:
- Zvysit `OLLAMA_TIMEOUT_S` v `.env` (predvolene: 1800 sekund = 30 minut).
- Pouzit mensi/rychlejsi model (zmenit `OLLAMA_MODEL` v `.env`).
- Znizit `MAX_CHUNK_CHARS` pre posielanie mensich casti do LLM.
