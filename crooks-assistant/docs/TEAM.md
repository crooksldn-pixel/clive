# The team on CLIVE

The people who work for CROOKS use CLIVE from their own phones for the day's work, at `/today` on CLIVE's own address. The owner hands out jobs and routines there, sees who did what, and lets each person in with his passkey. People CROOKS works with outside the team, a designer say, are on CLIVE's list too. They have no login, but CLIVE knows who to suggest for a job.

The owner's decisions of 1 October 2026, given in the review session:
- each member of the team signs in **on their own phone, with their own Tailscale login**;
- without his OK they may **mark orders packed, fulfil orders in Shopify, send email replies, and adjust stock from their counts**;
- they see **everything but his own conversations with CLIVE**.

And on 8 October (DEC-071, ruling 34): they may **send a draft he left**, on their own hold.

## Setting someone up

1. **First, limit what the team can reach.** Tailscale's default access rules let every user reach every device on the tailnet: your Mac, the build server, and anything listening on them. Before inviting anyone, change the rules in the admin console (Access controls) so that:
   - you keep everything;
   - the team reaches only CLIVE's machine, on port 443.

   For example, tag CLIVE's machine `tag:clive`, put the team's logins in `group:team`, and replace the default allow-all rule with two grants: one for you to everything, and one from `group:team` to `tag:clive` on port 443. Tailscale's own policy editor checks the file before saving it.
2. **Invite them to the tailnet.** In the Tailscale admin console go to Users, then Invite users, and send the invitation to the address they will sign in with. As of its April 2026 pricing, Tailscale's free Personal plan allows up to six users.
3. **They install Tailscale on their phone** and sign in with that same account.
4. **Tell CLIVE who they are**, in your own words. For example: "Mia works for us in the office: daily packing, emails, Instagram and general warehouse work. Her Tailscale login is …". CLIVE keeps a card for her. Her login then waits for you.
5. **Let them in.** Open Today and go to People. Tap *Let them in* beside their name and confirm with your passkey. Your passkey is set up once on the Connections screen (docs/CONNECTIONS.md).
6. **They open CLIVE's address** on their phone, `https://<your CLIVE>.<your tailnet>.ts.net`, and land on Today. Adding it to the home screen makes it an app.

To take someone off, open People and tap *Take access away*, confirmed with your passkey. You can also tell CLIVE they have left. Either way the door closes at their next request.

Someone who is not on the team is set up by the same words: "Henry does graphic design for us. His email is … and his Instagram is …; we use him for posters and post designs, not often product design." He gets a card, never a login. When a job needs a poster, CLIVE knows he is the one to suggest.

## What they see on Today

Rebuilt on 3 October, after George said the old screen was "a screen of buttons, not their own CLIVE". Today is now the team's own CLIVE:

- **CLIVE's line** at the top, beside the orb: one sentence that always says what happens next ("Pack these, then tap Packed or say “packed”").
- **The job in hand**, in big type, with one obvious action: *Take it*, *Packed*, *Done*, *Write the reply*, *Save the count*. Holding the card does the same as tapping its action. An order shows what goes in the box; an email or an Instagram message shows what the customer wrote.
- **After this**: the next few jobs, each one tap away, and *Every job* for the rest. Orders come first, then emails, then Instagram, then the other jobs. Jobs handed to them come before all of it.
- **Packed, waiting for tracking**, and **Done today**.
- **The ask bar**, on every screen. They can tap, type, or hold the button and speak:
  - a short sentence about one job is done at once: "I've packed 2106", "done with the hoodies", "I'll take the next one", "give it back", "undo";
  - anything else goes to their own CLIVE, whose answer comes back on the page, with any change as a card they confirm.
- **Undo for six seconds** after every step, in the bar at the foot of the screen. It takes back exactly the steps just taken (`/today/undo`). Steps CLIVE took for them in words can be undone the same way.

Speaking uses the phone's own speech recognition (Chrome on Android, Safari on an iPhone). The phone's speech service hears what they say and turns it into words: that is Google's on Chrome and Android, and Apple's on Safari and the iPhone, as with the keyboard's own dictation. CLIVE's Mac never gets the audio: only the words reach CLIVE, exactly as if they had been typed. The owner's voice allowance is never used, and the Mac still refuses a team member's recording, as it did before. On a phone without speech recognition, the button says so and they type. The People screen says this in one line, so George knows.

## What they can change, and how

Every change to the shop or the inbox comes up as a card, as it does for you. It shows what will happen: the order and the items, or the whole text of an email. The change is made only when they confirm it themselves, and it is recorded as theirs.

Without your OK, they may:
- **fulfil an order**, with its tracking number, and add tracking to one already fulfilled;
- **draft and send a reply** in an email thread someone wrote to CROOKS;
- **send a draft you left** in Gmail, exactly as you wrote it. CLIVE lists the drafts waiting and whose words each is; the card says *Words: George's* and *Sent by* them, and it goes only on their own hold. A draft another member of the team drafted with CLIVE is theirs or yours to send;
- **adjust stock** on a variant, up or down, to match what they counted.

Packing an order, entering a count and finishing a job are steps on the work list itself. They change nothing in Shopify.

They cannot, and CLIVE tells them it is your call. When they ask for one of these, the page or their CLIVE notes it for you on your list, in their words, and says "That's George's to do. I've told him." It is never tried and never shown as an error (`/today/flag`).
- refunds, cancellations, store credit and discounts;
- changing an order's address, items, notes or tags;
- a new email to anyone;
- archiving threads, and changes made in a batch.

They also never reach your conversations, your objectives, your screens and TVs, the engineering loop, Connections, or anyone's keys. The door refuses every route outside the team's own list, and the commit route refuses any change outside theirs, whatever card they hold.

## What you see

Your side of Today has four parts.

- **Team**:
  - **Waiting for you**: what the team asked you to do (a refund, a discount), in their words, with who asked and when. Tap *Done* when it is sorted.
  - **Packed, waiting for tracking**: orders someone has packed. *Fulfil* starts the sentence for your CLIVE with the order in it; you add the tracking number and confirm the card.
  - **The team now**: each person with what they have in hand and what they finished today. Tap a name for their day, step by step, and to cancel a job they have taken.
  - **Today, step by step**: every step, by whom. That covers who took and packed an order, who fulfilled it, who replied to an email, and who counted what. A change made through a card closes the job it was for, in the name of whoever confirmed it.
- **Work**: your own jobs and everything up for grabs, in the team's own view. You can take an order and pack it, finish a job, or say "packed 2109" in the ask bar.
- **Hand out**: one line for what needs doing, then who (anyone, or a name) and when. The choices are today, tomorrow, a day you pick, every day, weekdays, or one day each week. One switch makes it a stock count. Below are the repeating jobs, which you can stop, and the jobs not started yet, which you can cancel.
- **People**: the team and whether each person can use CLIVE. Let someone in, or take their access away, with your passkey. You can add someone with their name, the email they sign in to Tailscale with, and what they do. The people CLIVE can suggest are listed too, and one line says where the team's spoken words go.

## What is recorded about them

Tell each member of the team what CLIVE keeps:
- every step they take on a job;
- every change they confirm, with their login;
- their questions to CLIVE and its answers. These go in the turn log on the server, as yours do, with addresses, phone numbers and names taken out.

Their conversations are their own. You do not see them in your app, and they do not see yours.

## Not yet

- **Replying on Instagram.** CLIVE reads Instagram but cannot send there yet. They reply in the Instagram app, then mark the job done.
- **Vinted.** Uploading Vinted sales and shipping labels are jobs you hand out like any other. Doing them through CLIVE needs Vinted's Pro integrations, which are for Pro accounts and approved per account.
- **Telling them a job is waiting.** Today refreshes every thirty seconds while it is open; there is no phone notification yet.
- **Several people on the shared tablet.** The door decides who a request is, so the tablet acts as whoever is signed in to Tailscale on it. Signing in by invite link is a separate piece of work.

## Worth deciding before everyday use

Every member of the team's conversation with CLIVE runs on the owner's own Claude Max plan, as the builders do. The 30 September decision recorded the risk with the builders: Anthropic's consumer terms assume ordinary, individual use. Several people using one person's plan every day adds to that risk. If it bites, the fallback named then still applies: a Team plan or the API.

## How it is kept safe

- **The door's second rule** (`app/people/door.py`). A request the owner's rule refuses is let in as a member of the team only if all of these hold:
  - it came through Tailscale;
  - its login is one the owner let in with his passkey (`app/people/access.py`, kept beside his passkeys in the root-only directory);
  - the card is still staff and still active;
  - with `CROOKS_TAILSCALE_VERIFY` on, Tailscale confirms the device is theirs.
- **Only the team's routes** (`app/people/staff.py`): the chat, its cards, and Today. Every other route stays the owner's, and the route walk in `tests/test_team.py` fails if a new one is not.
- **A staff authority** (`app/tools/authority.py`) names its tools: the reads, the work list and the writes above. Anything else is refused before the gate is asked.
- **Their own assistant** (`app/people/prompt.py`, `app/runtime.py`) has their own prompt and offers only those tools. It is made again whenever their card changes.
- **Protected.** `app/people`, `app/routes/today.py` and their tests are on the engineering loop's protected paths, so a builder cannot widen any of this.
