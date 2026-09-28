# Manual Testing Checklist

## Test accounts

All accounts come from `python manage.py seed_demo_data`. The password is **`demopass123`** locally,
or whatever you passed as `--password` if you seeded prod with `--force`. Every email is a
`haewon201+<name>@gmail.com` alias, so any mail the site sends lands in the haewon201 Gmail inbox.

| Log in as | Roles | Team links | Why use this one |
|---|---|---|---|
| `haewon201+sandra.lee@gmail.com` (Sandra Lee) | Admin | — | Admin only. Should see all admin pages and no coach dashboard. |
| `haewon201+ryan.rickard@gmail.com` (Ryan Rickard) | Admin + Coach | Head coach of 12U, assistant on 10U | The league-owner case. Holds both roles, so both dashboards should work. Lands on the admin dashboard after login. |
| `haewon201+tom.nguyen@gmail.com` (Tom Nguyen) | Coach | Head coach of 10U **and** 12U | Plain coach on two teams, so this account tests the team switcher. Should never see fees. |
| `haewon201+shawn.lewis@gmail.com` (Shawn Lewis) | Coach + Parent | Head coach of 11U; parent of Kellen Lewis (11U) | Coach and parent in one account. Lands on the coach dashboard. Should also get a Parent nav link. |
| `haewon201+travis.roth@gmail.com` (Travis Roth) | Coach + Parent | Assistant coach on 11U; parent of Jack Roth (11U) | Assistant coach. Permissions should be identical to a head coach's. |
| `haewon201+katie.helstein@gmail.com` (Katie Helstein) | Parent | Parent of Carson Helstein (11U) | Plain parent on a team she doesn't coach. |
| `haewon201+james.brooks@gmail.com` (James Brooks) | Parent | Parent of Ethan Brooks (10U) | Has an **unclaimed second-parent invite** already, and a second parent (Patricia) is linked. |
| `haewon201+patricia.brooks@gmail.com` (Patricia Brooks) | Parent | Second parent of Ethan Brooks (10U) | Tests two parents on one kid. |

Other seeded parents follow the pattern `haewon201+<parentfirst>.<kidlast>@gmail.com` (e.g.
`robert.foster` for Liam Foster). Fees vary by kid: some are paid, some partially paid, some
unpaid.

**Seeded data worth knowing:**
- Teams: Choice Select 10U, 11U, 12U. All are 2026-2027, public, and accepting try-outs.
- Try-out signups: Carter Mills, Grace Nolan, Ella Pierce (10U); Henry Ortiz, Sebastian Quinn,
  Zoey Rhodes (12U). They are in mixed statuses and all start with an "undecided" decision.
- Each team has 4 weekly practices (the third one is **cancelled**) and a "Fall Classic" tournament
  about 30 days out.
- The home-page banner date is set to about 14 days from the seed date, so it should be visible.

**Not covered by the seed:**
- **Django admin (`/admin/`)**: no seeded user has `is_staff`. Run `python manage.py createsuperuser`
  first to test it.
- **Anonymous visitor**: use a private/incognito window.
- **If the site-wide password gate is on** (`SITE_BASIC_AUTH_ENABLED`), the browser asks for those
  credentials before any page loads.

---

## 1. Public pages (logged out)

- [ ] Home page loads, showing the mission text, the active try-out poster, and the Contact section
- [ ] Try-out announcement marquee shows when the next try-out date is within 30 days
- [ ] Footer shows the contact email and the Facebook link, and the Facebook link opens in a new tab
- [ ] Nav shows public links and "Log in", and no dashboard links
- [ ] **Schedule**: upcoming events are listed, and the team filter narrows the list
- [ ] Schedule: a cancelled practice shows a cancellation banner/badge
- [ ] **Teams index** lists only public teams, with seasons shown as "2026-2027"
- [ ] **Team detail** shows the roster with positions, coaches with Head/Assistant labels, and that team's schedule
- [ ] **Coaches index/detail**: bios and photos show, and each coach links to their teams
- [ ] Player detail for a player with a public profile shows name, photo, jersey number, position, team and description, and **no** date of birth, parent info or fees
- [ ] Player detail for a player **without** a public profile doesn't reveal their details to a logged-out visitor
- [ ] **Location** page shows the address and directions
- [ ] The site looks right at phone width, with no sideways scrolling and a usable nav

## 2. Try-out sign-up (logged out)

- [ ] `/try-outs/` shows the process description and the form
- [ ] The team dropdown lists only teams that are accepting try-outs
- [ ] Submitting with required fields blank shows errors inline, next to each field
- [ ] A valid submission (pick positions from the checkboxes) goes to the thank-you page
- [ ] The new signup appears in the admin try-out list under the right team/season with status "New"
- [ ] Deactivate all try-out posters (as admin), and the form shows as closed
- [ ] Turn off "accepting try-outs" on every team in Django admin, and the form shows as closed

## 3. Login and navigation

- [ ] Logging in with email + password works, and a wrong password shows an error
- [ ] Email is case-insensitive at login (e.g. try `Haewon201+Sandra.Lee@gmail.com`)
- [ ] After login, the redirect order is Admin → Coach → Parent (Ryan Rickard lands on Admin, Shawn Lewis on Coach, Katie on Parent)
- [ ] Nav shows **one link per role held** (Ryan: Admin + Coach; Shawn: Coach + Parent)
- [ ] Log out works, and dashboard URLs then redirect to the login page

## 4. Parent (Katie Helstein / James Brooks)

- [ ] The dashboard shows a card per kid with the next event and fee balance
- [ ] Clicking through to **payment history** shows a date/method/amount table with a running total
- [ ] The balance matches: paid, partially paid and unpaid kids each show the right amount and status
- [ ] **Edit player profile**: change the photo, description and public-profile setting; the changes show on the player detail page
- [ ] Turn the public profile off, and the player drops off the public view (check in an incognito window)
- [ ] Player detail as the parent shows date of birth and linked-parent contact info, but no fee ledger
- [ ] **Gallery**: add a photo; it appears on the player page and a large or phone photo comes out correctly rotated
- [ ] Gallery: delete a photo you added
- [ ] Katie can't open another kid's profile-edit or gallery URLs (try Ethan Brooks's player ID); the page should be forbidden or not found

## 5. Second-parent invite

- [ ] As James Brooks, open "Invite second parent". The **private-info warning** is shown and a copyable link appears
- [ ] Optionally enter an email and send it. The email arrives and the "emailed" state is shown
- [ ] Open the invite link logged out. The warning shows again and you can create an account
- [ ] After claiming, the new parent sees Ethan on their dashboard
- [ ] Opening the same link again shows the "invalid/used" page
- [ ] A made-up token URL shows the "invalid" page

## 6. Coach (Tom Nguyen, then Shawn Lewis)

- [ ] The dashboard shows a **team switcher** (Tom has 10U and 12U), with the role (Head/Assistant) shown per team
- [ ] **Roster**: add a player, then edit name, date of birth, jersey number and positions
- [ ] Roster: removing a player takes them off the roster, but the player record isn't deleted
- [ ] Roster: **bulk move** checked players to another team; they appear on the other team with their positions intact
- [ ] **Practices**: add, edit, cancel (status) and delete a practice; changes show on the public schedule
- [ ] **Tournaments**: add, edit and delete work (coaches can now edit tournaments)
- [ ] **Try-Out Sign-Ups**: all teams and all years are visible, and the team filter works
- [ ] Status and Decision dropdowns are **editable only on this coach's own teams' rows**; other rows show plain text
- [ ] Changing Status shows a confirm dialog and then saves; changing Decision saves right away with no dialog
- [ ] **No fees** appear anywhere for Tom (and `/accounts/dashboard/admin/fees/` is forbidden)
- [ ] Travis Roth (an assistant) can do everything Shawn (head coach) can on 11U
- [ ] Tom can't open the 11U roster by URL (swap the team ID into the address); it should be forbidden or not found

## 7. Admin (Sandra Lee, then Ryan Rickard)

- [ ] **Try-out list**: the year/season filter works, and the Status dropdown with confirm dialog saves and records history
- [ ] **Try-out detail**: status and decision history both show, with who changed each and when
- [ ] **Fees**: create a fee for a single player
- [ ] Fees: create a **team-wide** fee; one full-amount fee appears for each player on that team, and the confirmation message gives the count
- [ ] Fees: record a payment inline; the ledger and balance update without a full page reload
- [ ] Fees: the "outstanding only" filter hides fully paid fees
- [ ] Fees: editing a fee's amount updates the balance
- [ ] **Coach bios**: edit a bio or photo; it changes on the public Coaches page
- [ ] **Schedule management**: can manage practices and tournaments for **any** team, including teams the admin doesn't coach
- [ ] Roster: an admin can edit any team's roster
- [ ] **Try-out posters**: upload, edit and delete work, and the active poster shows on the home page
- [ ] Posters: activating a second poster while one is already active is rejected with a pop-up
- [ ] Player detail as admin shows the fee ledger, full parent-link history, and a link back to the try-out signup (for promoted players)
- [ ] Ryan Rickard can also reach his coach dashboard (12U head, 10U assistant)

## 8. End-to-end: try-out → roster

Use a fresh signup from section 2, or a seeded one such as Carter Mills (10U), with Tom Nguyen as coach.

- [ ] The coach sets the Decision to **Invite**, and a "Send Acceptance Email" button appears
- [ ] Clicking Send shows a confirm dialog, the email arrives, and the button locks with a "Sent" badge
- [ ] Changing the decision afterwards resets the button so it can be sent again
- [ ] Open the link in the email while logged out; the respond page shows Accept/Decline
- [ ] **Accept**: set a password in the same visit, and you're logged in as that parent
- [ ] The kid now appears on the **team roster** with the positions from the sign-up, and on the new parent's dashboard
- [ ] Opening the respond link again shows it as used/invalid
- [ ] A **Not Selected** decision sends a rejection email, and **Decline** on the respond page records the decline without creating a player
- [ ] For a signup with no date of birth, accepting does *not* create a player. Add the date of birth in Django admin, then **Promote to Roster** on the admin detail page works

## 9. Permission spot-checks

Paste these URLs while logged in as the wrong user. Each should show forbidden or not found, never the page.

- [ ] Parent (Katie) → `/accounts/dashboard/coach/`, `/accounts/dashboard/admin/`
- [ ] Coach only (Tom) → `/accounts/dashboard/admin/fees/`, `/accounts/dashboard/admin/tryouts/`
- [ ] Admin only (Sandra) → `/accounts/dashboard/coach/`, which should show no coach dashboard, since she has no coach role
- [ ] Logged out → any `/accounts/dashboard/...` URL redirects to the login page
- [ ] Coach (Tom) → the 11U practices/roster URLs (a team he doesn't coach)

## 10. Django admin (`/admin/`, needs a superuser)

- [ ] Adding a user asks for name and roles up front
- [ ] Team page: the **Publish/Unpublish** button toggles public visibility; an unpublished team disappears from Teams, Coaches, Schedule and public player profiles
- [ ] A coach whose only team is unpublished still appears on Coaches, with the team shown as "TBA"
- [ ] Parent-player links can be managed here, and removed links stay visible as history
- [ ] Try-out status history is read-only

## 11. Deployed site only

- [ ] Uploaded images (posters, player and gallery photos, coach photos) load from R2 and aren't broken
- [ ] Emails actually send from Resend (check the haewon201 inbox)
- [ ] Forms submit without CSRF errors on `choiceselectleague.org` and `www.`
- [ ] The password gate, if it's on, prompts once and then the site works normally
