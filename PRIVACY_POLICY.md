# BusNeighbor — Privacy Policy

**Effective date:** `August 29, 2026`

BusNeighbor is a free app that shows Philadelphia public transit vehicle positions, service alerts, and a map. It is built for the general public to enjoy, but with thoughtful touches for blind and low-vision riders. This policy explains what BusNeighbor does with information on your phone, and what it sends over the network and to whom.

BusNeighbor is published by `Joseph D. Mirarchi`, an individual. There is no company behind it and no one else has access to anything the app does. You can reach me at **bus@dydx.org**.

---

## The short version

- **No accounts, no advertising, no analytics, no crash reporting, no tracking.**
- **Your location never leaves your device.** It is used only to draw the map and to speak the nearest stop, and only while you are using the app.
- BusNeighbor does fetch transit data and map images over the internet. Like any app that loads data, those requests reveal your device's IP address and what you asked for. The table below says exactly what each service can see.
- **Nothing about you is stored on any server, and nothing is ever sold or shared for advertising.**
- If you download the offline map, BusNeighbor stops making map requests entirely.

---

## What stays on your device

### Your location

You have the option to use BusNeighbor without granting location permission. If you choose to grant location permission, BusNeighbor uses your device's location to:

- center the map where you are,
- show which vehicles are near you, and
- announce the nearest SEPTA stop and its distance, so you can orient yourself.

All three happen **entirely on your device**. Your location is held only in the app's memory while the app is running. It is never written to storage, never included in any network request, and never transmitted to me or to anyone else.

BusNeighbor uses location **only while you are using the app**. It does not request or use background location.

Location permission is optional. If you decline it, the app still works: the map opens at Philadelphia City Hall and every other feature behaves normally.

### Nearest-stop announcements

The nearest-stop announcement is computed on your device from a list of pre-populated stops built into the app. No internet connection is needed for it, and nothing is sent anywhere to produce it.

### Your settings

Your route selections, map style, marker style, and accessibility preferences are saved on your device, using your operating system's standard app-preferences storage. **They are never sent to me.**

Your phone may include them in its own system backup — to your iCloud or Google account, under your control and governed by Apple's or Google's terms. That is what lets your settings come back if you restore or replace your device. You can turn this off in your device's backup settings. I have no access to those backups.

### Map data on your device

If you choose to download the offline map, roughly 28 MB of map data is stored on your device. Map tiles you have viewed may also be cached on your device so they load faster and use less data. Both are removed when you uninstall the app, and both can be cleared from within the app.

---

## What leaves your device, and who receives it

BusNeighbor is a client for public data. To show you where the buses are, it has to ask someone. Every request carries your device's IP address — that is how the internet works, and it is true of every app that loads anything.

Here is every service BusNeighbor contacts, and the most that each one can see.

| Service                                 | Who runs it                  | Why BusNeighbor contacts it                                                                                  | What that service can see                                                                                                                         |
| --------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| **BusNeighbor vehicle-position mirror** | Me, using Cloudflare Workers | To fetch real-time vehicle positions and service alerts, mirrored from SEPTA                                 | Your IP address and the time of the request. The file covers the entire SEPTA system, so **the request does not reveal which routes you follow**. |
| **SEPTA** (`www3.septa.org`)            | SEPTA                        | To fetch detour and trip details for specific routes                                                         | Your IP address, the time of the request, and **which routes you asked about**                                                           |
| **GitHub Releases** (`jos-eph/lovmaps`) | GitHub, Inc.                 | To download the offline map, or — if you have not downloaded it — to stream pieces of it as you move the map | Your IP address, and, when streaming, **which portions of the map file you request**, which corresponds to the areas you pan to                   |

All of these requests use HTTPS.

**Two things follow from this table that are worth saying plainly.** 
* First, whenever you pan the map without having downloaded the offline map, some third party learns roughly which part of the Philadelphia area you were looking at — not because BusNeighbor tells them where you are, but because you asked them for that piece of the map. Downloading the offline map fully removes this concern. 
* Second, if you select specific routes, SEPTA can see which ones.

### About the mirror I operate

The vehicle-position mirror is mine. It runs as a Cloudflare Worker under my Cloudflare account, which means Cloudflare operates the servers that receive your request and acts as my service provider in doing so.

I have not turned on request logging or log export for that Worker, so **no record of individual requests is kept for me to look at**. Cloudflare shows me aggregate counts — how many requests came in, how much bandwidth was used — which do not identify anyone. I do not have, do not keep, and do not want a list of who used the app or when.

### About the other services

I do not send these services anything about you beyond what your device's own request contains, and I receive nothing back from them about you. Each one operates independently and handles what it receives under its own privacy policy, which I neither control nor can see into:

- **SEPTA** — <https://www.septa.org/privacy/>
- **GitHub** — <https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement>

---

## What BusNeighbor never does

- **No advertising**, and no advertising identifiers.
- **No analytics or usage tracking** of any kind.
- **No crash reporting.**
- **No accounts, no sign-in, no email collection.**
- **No sale or sharing of personal information** — there is nothing to sell.
- **No tracking of you** across other apps or websites.
- **No background location.**
- **No transmission of your location**, to anyone, for any purpose.

---

## Sharing with third parties

**BusNeighbor does not share user data with any third party.** No analytics service, advertising network, data broker, or third-party SDK receives anything from this app, because no such component is in it. The services in the table above are not given user data by BusNeighbor; they see only what your device's own network request necessarily contains.

---

## Keeping and deleting information

**I hold no data about you, so there is nothing on my side to retain or delete.** There is no account to close and no deletion request to make.

On your device:

- **Settings** are deleted from the device when you uninstall the app. A copy may remain in your own phone's system backup, which you control.
- **Downloaded map data and cached tiles** can be cleared from within the app, and are deleted when you uninstall it.
- **Your location** is never stored at all — not by the app, not by me.

The services listed in the table keep their own server logs under their own retention policies. I have no access to those logs and cannot delete anything from them on your behalf.

---

## Your choices

- **Location permission** can be granted or revoked at any time in your device's settings. BusNeighbor is fully usable even if you revoke location permission.
- **Downloading the offline map** stops BusNeighbor from requesting map data over the network at all. If you would rather not have GitHub see which areas you look at, this is how you prevent it. I recommend that all users download the offline map.
- **Uninstalling the app** removes everything it stored on the device. If your phone backed up your settings to your own iCloud or Google account, you control that copy through your device's backup settings.

---

## Children

BusNeighbor is a general-audience transit app. It is not directed to children, and it does not knowingly collect information from anyone, including children under 13.

---

## Where BusNeighbor is available

BusNeighbor is distributed in the United States only. It is not offered in the European Union or the United Kingdom. Because it is built around the SEPTA network, all intended users are in Pennsylvania, New Jersey, and Delaware.

New Jersey and Delaware have comprehensive consumer privacy laws. Pennsylvania does not. Those laws reach organizations holding personal data about tens of thousands of a state's residents — and **I hold personal data about no one.** No threshold is met, and no reading of any of them changes a word of this policy.

If you live in New Jersey or Delaware and want to exercise a privacy right — to see, correct, or delete what I hold about you — there is nothing to act on, because there is nothing held. Write to me at the address below if you would like that confirmed directly.

---

## Changes to this policy

If BusNeighbor's data practices change, this policy will be updated **in the same release that changes them** — never afterward — and the effective date above will change. Material changes will also be noted in the app's release notes. A short list of past revisions is kept at the bottom of this page.

---

## Contact

Questions about this policy, or about privacy in BusNeighbor:

**bus@dydx.org**

---

*Map data © OpenStreetMap contributors, available under the [Open Database License](https://www.openstreetmap.org/copyright). Transit data is provided by SEPTA. BusNeighbor is not affiliated with or operated by SEPTA.*

---

## Revision history

| Date            | What changed     |
| --------------- | ---------------- |
| August 29, 2026 | First published. |
