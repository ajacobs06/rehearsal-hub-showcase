import { PRIVACY_CONTACT } from './api'

/** Public privacy notice (UK GDPR), readable before sign-in. */
export default function Privacy({ back }: { back: React.ReactNode }) {
  return (
    <article className="prose">
      {back}
      <h1>Privacy notice</h1>
      <p className="muted small">Rehearsal Hub, University of Birmingham Barbershop Singing Society. Last updated 26 September 2026.</p>

      <h2>Who we are</h2>
      <p>
        Rehearsal Hub is run by the University of Birmingham Barbershop Singing Society (BSS), a student society. The
        society's committee decides how this data is used. Questions or requests go to{' '}
        <a href={`mailto:${PRIVACY_CONTACT}`}>{PRIVACY_CONTACT}</a>.
      </p>

      <h2>What we store</h2>
      <ul>
        <li>Your name and the email address you sign in with.</li>
        <li>Your usual voice part, any different part you pick for a song, and the groups you're in (such as the auditioned chorus).</li>
        <li>How far you've got with each song (not started, learning, learned or ready).</li>
        <li>Your replies to rehearsals (going, maybe or can't go).</li>
        <li>Any feedback you send through the site.</li>
        <li>For committee members: your name on announcements you post.</li>
      </ul>
      <p>
        We never see or store your password. Signing in uses one cookie, which is needed for the site to work. There are
        no advertising or analytics cookies.
      </p>

      <h2>Why we use it</h2>
      <p>
        To run the society's rehearsals: so you can learn your part, the committee can see which parts are ready and who's coming,
        and we can fix problems you report. Our lawful basis is the society's legitimate interest in organising rehearsals for
        its members.
      </p>

      <h2>Who can see it</h2>
      <ul>
        <li>Committee members with admin access can see members' names, emails, parts, groups, progress, replies and feedback.</li>
        <li>Other members only see totals, such as how many people are going to a rehearsal, never your individual details.</li>
        <li>Members see the name of the committee member who posted each announcement.</li>
        <li>
          Our service providers process it for us: Microsoft Azure stores it in France Central (in the EU) and sends invite emails, and
          Google or Microsoft (Entra External ID, for email and password accounts) handles sign-in.
        </li>
        <li>The Azure account that runs Rehearsal Hub belongs to the society, not the university.</li>
      </ul>

      <h2>Error monitoring</h2>
      <p>
        To find and fix problems, the server records technical details of requests and errors (for example which page failed and
        when). IP addresses are masked, nothing is tracked in your browser, and these records are deleted after 30 days.
      </p>
      <p>
        For security, we also log changes to stored files and settings, such as who uploaded or deleted a score and from which IP
        address. Only committee admins upload files. These logs are deleted after 30 days.
      </p>

      <h2>How long we keep it</h2>
      <p>
        We keep your data while you're a member. When you leave, the committee removes your account and everything linked to it.
        If you sign in with an email and password, that sign-in account (held by Microsoft) is deleted at the same time. If you
        create one without being invited, it's deleted as soon as you try to sign in. The committee reviews the member list
        each September. Announcements you posted stay up after you leave, signed "Committee" instead of your name. Deleted data
        can stay in short-term backups for up to 7 days.
      </p>

      <h2>Your rights</h2>
      <ul>
        <li>See your data: download everything we hold about you from the Your data page.</li>
        <li>Delete it: remove your account from the Your data page, or ask the committee.</li>
        <li>Correct it: change your part yourself, or ask the committee to fix anything else.</li>
        <li>Object to how we use it, by emailing {PRIVACY_CONTACT}.</li>
      </ul>
      <p>
        If you're unhappy with how we've handled your data, you can complain to the Information Commissioner's Office at{' '}
        <a href="https://ico.org.uk/make-a-complaint/" target="_blank" rel="noreferrer">
          ico.org.uk
        </a>
        .
      </p>
    </article>
  )
}
