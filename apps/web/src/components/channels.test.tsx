import type { GoogleChatSpace, GoogleChatSpaceList, SlackChannelList } from "@cairn/api-client";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import {
  ChannelPicker,
  ChannelPickerLoading,
  reconcileChannels,
  reconcileSpaces,
  SpacePicker,
  SpacePickerLoading,
} from "./ChannelPicker.js";
import { GOOGLE_CHAT_NO_HISTORY, SLACK_INVITE_RULE } from "./ConnectionCard.js";

/**
 * The Slack channel picker, and the one rule it exists to enforce: **a tick
 * means the backend said so.**
 *
 * Every other multi-select in every other product ticks on click and reconciles
 * afterwards, and for a filter that is the right trade. This control is a claim
 * about surveillance. A channel drawn as selected when the save was refused
 * tells somebody CAIRN is reading a room it is not — and they will act on that,
 * because the whole product is built on the premise that this screen is
 * accurate. Three tests below are about that and nothing else.
 *
 * The rest is the ordinary contract of a list somebody has to be able to use:
 * it filters, it works from the keyboard without losing the reader's place, it
 * explains itself to a role that cannot change it, and it never renders a
 * channel name that did not come from the server — Slack's message events carry
 * IDs only, so a name here can only be one the backend returned.
 *
 * Rendered with bare `render`: the picker touches no client, session or route.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

/**
 * The `/invite` requirement in the server's own words.
 *
 * Copied from the API's `BOT_INVITE_NOTICE` rather than paraphrased, because the
 * point of the field is that this sentence has exactly one author. A test that
 * matched a paraphrase would keep passing on the day the backend changed it,
 * which is the failure the field exists to prevent.
 */
const NOTICE =
  "CAIRN only receives messages from channels the CAIRN app has been added to. " +
  "For each channel you select, run /invite @CAIRN in Slack. CAIRN cannot add " +
  "itself — it does not ask Slack for permission to join channels.";

const SELECTION: SlackChannelList = {
  channels: [
    { id: "C001", name: "general", botIsMember: true, selected: true },
    { id: "C002", name: "engineering", botIsMember: false, selected: false },
    { id: "C003", name: "design", botIsMember: true, selected: false },
  ],
  notice: NOTICE,
};

/** The same list with nothing chosen. */
function nothingChosen(): SlackChannelList {
  return {
    channels: (SELECTION.channels ?? []).map((channel) => ({ ...channel, selected: false })),
    notice: NOTICE,
  };
}

function open(): Promise<void> {
  return userEvent.click(screen.getByRole("button", { name: /choose channels/i }));
}

describe("what the picker shows before it is opened", () => {
  it("answers 'what is CAIRN reading' in one sentence, with the names the backend gave", () => {
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} />);

    expect(screen.getByText(/cairn is reading 1 channel: #general\./i)).toBeVisible();
  });

  it("says nothing is being read when nothing is chosen", () => {
    render(<ChannelPicker selection={nothingChosen()} canManage onToggle={vi.fn()} />);

    expect(
      screen.getByText(/no channels chosen, so cairn is reading nothing from slack/i),
    ).toBeVisible();
  });

  it("names every chosen channel, because the API names every chosen channel", () => {
    // `selected` is a property of the channel rather than a parallel array of
    // IDs, so a chosen channel is by construction one the server also named.
    // There is no counted-but-unnamed case for the summary to round in either
    // direction — which is the whole reason the API is shaped that way.
    render(
      <ChannelPicker
        selection={{
          channels: [
            { id: "C001", name: "general", botIsMember: true, selected: true },
            { id: "C002", name: "engineering", botIsMember: true, selected: true },
          ],
          notice: NOTICE,
        }}
        canManage
        onToggle={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/cairn is reading 2 channels: #general, #engineering\./i),
    ).toBeVisible();
  });
});

describe("choosing channels", () => {
  it("states the invite rule where the choosing happens", async () => {
    // **The single most important sentence in this component.** CAIRN does not
    // request `channels:join`, so Slack sends nothing from a channel the app has
    // not been invited to. Without this, somebody selects four channels, sees
    // nothing arrive, and concludes the product is broken — and from the screen
    // alone that is the only available explanation.
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} />);
    await open();

    expect(screen.getByText(NOTICE)).toBeVisible();
  });

  it("prints the server's sentence rather than a second copy of it", async () => {
    // The API sends `notice` with every channel response precisely so there is
    // one author for the rule the backend actually enforces. A hardcoded
    // duplicate would keep rendering the old wording — confidently, and
    // eventually wrongly — long after the server changed what it does.
    render(
      <ChannelPicker
        selection={{ ...SELECTION, notice: "Ask an administrator to add CAIRN in Slack." }}
        canManage
        onToggle={vi.fn()}
      />,
    );
    await open();

    expect(screen.getByText(/ask an administrator to add cairn in slack/i)).toBeVisible();
    expect(screen.queryByText(SLACK_INVITE_RULE)).not.toBeInTheDocument();
  });

  it("says collection starts now and imports no history", async () => {
    // "We imported your last 90 days" is what people assume a connection does,
    // and discovering otherwise a week later reads as data loss.
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} />);
    await open();

    expect(screen.getByText(/there is no history import/i)).toBeVisible();
  });

  it("filters the list by what is typed", async () => {
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} />);
    await open();

    await userEvent.type(screen.getByRole("searchbox", { name: /search channels/i }), "eng");

    expect(screen.getByRole("checkbox", { name: /engineering/i })).toBeVisible();
    expect(screen.queryByRole("checkbox", { name: /general/i })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 of 3 channels match.");
  });

  it("tolerates the # somebody types out of habit", async () => {
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} />);
    await open();

    await userEvent.type(screen.getByRole("searchbox", { name: /search channels/i }), "#design");

    expect(screen.getByRole("checkbox", { name: /design/i })).toBeVisible();
  });

  it("says a search matched nothing, rather than showing an empty box", async () => {
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} />);
    await open();

    await userEvent.type(screen.getByRole("searchbox", { name: /search channels/i }), "zzz");

    expect(screen.getByText(/no public channel matches/i)).toBeVisible();
  });

  it("says so when Slack listed no public channels at all", async () => {
    render(
      <ChannelPicker selection={{ channels: [], notice: NOTICE }} canManage onToggle={vi.fn()} />,
    );
    await open();

    expect(screen.getByText(/slack returned no public channels for this workspace/i)).toBeVisible();
  });

  it("reports the choice to the caller rather than deciding it itself", async () => {
    const onToggle = vi.fn();
    render(<ChannelPicker selection={SELECTION} canManage onToggle={onToggle} />);
    await open();

    await userEvent.click(screen.getByRole("checkbox", { name: /design/i }));

    expect(onToggle).toHaveBeenCalledWith("C003", true);
  });

  it("reports a de-selection as one", async () => {
    const onToggle = vi.fn();
    render(<ChannelPicker selection={SELECTION} canManage onToggle={onToggle} />);
    await open();

    await userEvent.click(screen.getByRole("checkbox", { name: /general/i }));

    expect(onToggle).toHaveBeenCalledWith("C001", false);
  });
});

describe("a tick means the backend confirmed it", () => {
  it("does not tick a channel whose save has not come back", async () => {
    // **The test this component exists for.** The click has happened, the
    // request is in flight, and the honest answer to "is CAIRN reading #design"
    // is still no. An optimistic tick answers yes, and somebody acts on it.
    const onToggle = vi.fn();
    render(<ChannelPicker selection={SELECTION} canManage onToggle={onToggle} saving={["C003"]} />);
    await open();

    const design = screen.getByRole("checkbox", { name: /design/i });
    expect(design).not.toBeChecked();
    expect(design).toHaveAttribute("aria-busy", "true");
  });

  it("says a save is in flight rather than leaving the row apparently idle", async () => {
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} saving={["C003"]} />);
    await open();

    expect(
      screen.getByText(/nothing changes until slack and cairn both confirm it/i),
    ).toBeVisible();
  });

  it("ticks exactly the channels the backend returned as selected", async () => {
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} />);
    await open();

    expect(screen.getByRole("checkbox", { name: /general/i })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /engineering/i })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /design/i })).not.toBeChecked();
  });

  it("says which channels the app is not in yet, because those deliver nothing", async () => {
    // **The most common reason somebody connects Slack and sees nothing.** CAIRN
    // asks for no `channels:join`, so a channel chosen while `botIsMember` is
    // false stays silent forever — silently, which is the part that makes it
    // unanswerable from the screen. A channel the app *is* in and nobody chose
    // says nothing: "waiting for an invite" against a channel that is fine sends
    // somebody to Slack to fix a problem they do not have.
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} />);
    await open();

    expect(screen.getByRole("checkbox", { name: /engineering/i })).toHaveAccessibleDescription(
      /the cairn app is not in this channel/i,
    );
    expect(screen.getByRole("checkbox", { name: /engineering/i })).toHaveAccessibleDescription(
      /run \/invite @CAIRN there/i,
    );
    expect(screen.getByRole("checkbox", { name: /design/i })).toHaveAccessibleDescription("");
  });

  it("confirms the app is in a channel that was chosen", async () => {
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} />);
    await open();

    expect(screen.getByRole("checkbox", { name: /general/i })).toHaveAccessibleDescription(
      /the cairn app is in this channel/i,
    );
  });

  it("says so when a choice could not be saved", async () => {
    render(
      <ChannelPicker
        selection={SELECTION}
        canManage
        onToggle={vi.fn()}
        problem={{ message: "CAIRN could not reach the server, so it could not save that." }}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not reach the server/i);
  });
});

describe("what a role is offered", () => {
  it("shows a Member or Viewer the same channels, read-only, and says who chooses", () => {
    // Absence is not an explanation. Which rooms CAIRN reads is a fact about
    // this reader's own messages, so a summary they cannot expand is one they
    // have to take on trust.
    render(<ChannelPicker selection={SELECTION} canManage={false} />);

    expect(screen.getByText(/cairn is reading 1 channel: #general\./i)).toBeVisible();
    expect(screen.getByText("#general")).toBeVisible();
    expect(screen.queryByRole("button", { name: /choose channels/i })).not.toBeInTheDocument();
    expect(
      screen.getByText(
        /an owner or an admin of this workspace chooses which channels cairn reads/i,
      ),
    ).toBeVisible();
  });

  it("names the read-only list, in the same words the space picker uses", () => {
    // "Selected channels" and "Selected spaces" are one pair of words across
    // both providers: a reader moving between the Slack card and the Google
    // Chat card is looking at one product, not two screens that were built
    // separately. It names the list for a screen reader too, which otherwise
    // meets a bare `<ul>` after a sentence and has to infer the relation.
    render(<ChannelPicker selection={SELECTION} canManage={false} />);

    expect(screen.getByRole("list", { name: /selected channels/i })).toBeVisible();
  });

  it("takes a note for a surface where somebody else decides", () => {
    render(
      <ChannelPicker
        selection={SELECTION}
        canManage={false}
        readOnlyNote="These are chosen on the workspace screen."
      />,
    );

    expect(screen.getByText(/chosen on the workspace screen/i)).toBeVisible();
  });

  it("offers no control to a role with no handler, whatever it was told about itself", () => {
    // Belt and braces: `canManage` is the role's answer and `onToggle` is the
    // surface's. A control with nowhere to send the choice is a dead end.
    render(<ChannelPicker selection={SELECTION} canManage />);

    expect(screen.queryByRole("button", { name: /choose channels/i })).not.toBeInTheDocument();
  });
});

describe("keyboard and focus", () => {
  it("can be opened and driven without a mouse", async () => {
    const onToggle = vi.fn();
    render(<ChannelPicker selection={SELECTION} canManage onToggle={onToggle} />);

    await userEvent.tab();
    expect(screen.getByRole("button", { name: /choose channels/i })).toHaveFocus();
    await userEvent.keyboard("{Enter}");

    // Focus lands in the search box: somebody who just asked to choose channels
    // wants to be typing, not tabbing through two hundred checkboxes.
    expect(screen.getByRole("searchbox", { name: /search channels/i })).toHaveFocus();

    await userEvent.tab();
    expect(screen.getByRole("checkbox", { name: /general/i })).toHaveFocus();
    await userEvent.keyboard(" ");

    expect(onToggle).toHaveBeenCalledWith("C001", false);
  });

  it("puts focus back on the trigger when the picker is closed", async () => {
    // Without this, closing drops a keyboard reader at the top of the document
    // and they have to tab all the way back to where they were working.
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} />);

    await open();
    await userEvent.click(screen.getByRole("button", { name: /done choosing channels/i }));

    expect(screen.getByRole("button", { name: /choose channels/i })).toHaveFocus();
  });

  it("tells assistive technology whether the picker is open", async () => {
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} />);

    const trigger = screen.getByRole("button", { name: /choose channels/i });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await open();

    expect(screen.getByRole("button", { name: /done choosing channels/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("names each checkbox after the channel and nothing else", async () => {
    // The state hangs off `aria-describedby`, not off the label: folding
    // "Saving" into the name announces the control as a different control every
    // time its state changes.
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} saving={["C001"]} />);
    await open();

    expect(screen.getByRole("checkbox", { name: "#general" })).toBeInTheDocument();
  });
});

describe("loading", () => {
  it("announces what is loading, since a skeleton says nothing", () => {
    render(<ChannelPickerLoading />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading the Slack channels.");
  });

  it("hides the placeholders themselves from assistive technology", () => {
    const { container } = render(<ChannelPickerLoading />);

    expect(container.querySelectorAll("[aria-hidden='true']")).toHaveLength(2);
  });
});

describe("accessibility", () => {
  it("passes an axe audit with the picker open", async () => {
    const { container } = render(
      <ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} saving={["C002"]} />,
    );
    await open();

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("passes an axe audit in its failed state", async () => {
    const { container } = render(
      <ChannelPicker
        selection={SELECTION}
        canManage
        onToggle={vi.fn()}
        problem={{ message: "That could not be saved.", requestId: "req_01H9" }}
      />,
    );

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("passes an axe audit read-only", async () => {
    const { container } = render(<ChannelPicker selection={SELECTION} canManage={false} />);

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("groups the checkboxes under a name", async () => {
    render(<ChannelPicker selection={SELECTION} canManage onToggle={vi.fn()} />);
    await open();

    const group = screen.getByRole("group", { name: /public channels cairn reads/i });
    expect(within(group).getAllByRole("checkbox")).toHaveLength(3);
  });
});

describe("folding a save back onto the list", () => {
  /**
   * `PUT /channels` answers with IDs and no names — deliberately, because names
   * are `conversations.list`'s to give and not a write endpoint's. These tests
   * are about the one function that turns that answer back into ticks, because
   * it is the only place in the client where a tick is decided at all.
   */

  it("ticks exactly what the server confirmed", () => {
    const next = reconcileChannels(SELECTION, {
      channelIds: ["C001", "C003"],
      notice: NOTICE,
    });

    expect(next.channels).toEqual([
      { id: "C001", name: "general", botIsMember: true, selected: true },
      { id: "C002", name: "engineering", botIsMember: false, selected: false },
      { id: "C003", name: "design", botIsMember: true, selected: true },
    ]);
  });

  it("unticks a channel the server left out of its answer", () => {
    // **The direction that must work.** The request was the full state of the
    // checkboxes, so an ID missing from the reply is permission withdrawn — not
    // a channel the server forgot to mention. Treating it as an omission would
    // leave a tick standing against a room CAIRN has stopped reading.
    const next = reconcileChannels(SELECTION, { channelIds: [], notice: NOTICE });

    expect(next.channels?.every((channel) => !channel.selected)).toBe(true);
  });

  it("treats an answer with no channelIds at all as nothing selected", () => {
    // The field is optional in the schema, and the honest reading of its absence
    // is "no channels", which is also what the endpoint means by an empty list.
    const next = reconcileChannels(SELECTION, { notice: NOTICE });

    expect(next.channels?.every((channel) => !channel.selected)).toBe(true);
  });

  it("takes the notice from the response that is now current", () => {
    const next = reconcileChannels(SELECTION, {
      channelIds: ["C001"],
      notice: "Run /invite @CAIRN in each one.",
    });

    expect(next.notice).toBe("Run /invite @CAIRN in each one.");
  });

  it("invents no channel for an ID it was never given a name for", () => {
    // Slack's message events carry IDs and no names, so a name on this screen
    // can only be one `conversations.list` returned. `C999` is not a name, and a
    // row labelled `C999` would be a channel nobody can recognise.
    const next = reconcileChannels(SELECTION, {
      channelIds: ["C001", "C999"],
      notice: NOTICE,
    });

    expect(next.channels?.map((channel) => channel.id)).toEqual(["C001", "C002", "C003"]);
  });

  it("keeps the ticks it decides out of the caller's hands entirely", () => {
    // The list handed in is not mutated: the previous render's data is what a
    // failed save has to fall back to, and a function that edited it in place
    // would leave the fallback already showing the change that did not happen.
    const before = structuredClone(SELECTION);
    reconcileChannels(SELECTION, { channelIds: [], notice: "different" });

    expect(SELECTION).toEqual(before);
  });
});

/**
 * The Google Chat space picker.
 *
 * The same control as the channel picker, dressed in the other provider's
 * vocabulary, and it must enforce the same rule: **a tick means the backend said
 * so.** Two things are genuinely different about Google and both are here.
 *
 * - **Selected is not the same as delivering.** Google Chat carries events
 *   through subscriptions that expire on Google's schedule and renew
 *   automatically, and a renewal fails whenever the authorising account loses
 *   access. A space drawn as fine while its subscription is suspended is the
 *   exact failure this picker exists to prevent, so the state is carried per
 *   space and said as a word.
 * - **An ineligible space is shown, not hidden.** A space missing from the list
 *   is indistinguishable from one that does not exist, and "why is Incidents not
 *   here" is a question the screen should answer rather than raise.
 */
describe("the Google Chat space picker", () => {
  /** The server's own standing sentence, as the API sends it with every list. */
  const SPACE_NOTICE =
    "CAIRN reads a space only from the moment you select it, and only while its Google subscription is active.";

  const SPACES: GoogleChatSpaceList = {
    spaces: [
      {
        name: "spaces/AAAA1",
        displayName: "Platform",
        eligible: true,
        selected: true,
        subscriptionState: "active",
        expireTime: "2026-09-01T09:00:00Z",
        errorCategory: null,
      },
      {
        name: "spaces/AAAA2",
        displayName: "Design",
        eligible: true,
        selected: false,
        subscriptionState: null,
        expireTime: null,
        errorCategory: null,
      },
      {
        name: "spaces/AAAA3",
        displayName: "Ali and Jo",
        eligible: false,
        selected: false,
        subscriptionState: null,
        expireTime: null,
        errorCategory: "configuration_invalid",
      },
    ],
    notice: SPACE_NOTICE,
  };

  /** One space, with whatever this test needs to be true of it. */
  function oneSpace(space: Partial<GoogleChatSpace>): GoogleChatSpaceList {
    return {
      spaces: [
        {
          name: "spaces/AAAA1",
          displayName: "Platform",
          eligible: true,
          selected: true,
          subscriptionState: null,
          expireTime: null,
          errorCategory: null,
          ...space,
        },
      ],
      notice: SPACE_NOTICE,
    };
  }

  function openSpaces(): Promise<void> {
    return userEvent.click(screen.getByRole("button", { name: /choose spaces/i }));
  }

  it("answers 'what is CAIRN reading' before any control, with the names Google gave", () => {
    render(<SpacePicker spaces={SPACES} canManage onToggle={vi.fn()} />);

    expect(screen.getByText(/cairn is reading 1 space: platform\./i)).toBeVisible();
  });

  it("says nothing is being read when nothing is chosen", () => {
    render(
      <SpacePicker
        spaces={{
          ...SPACES,
          spaces: (SPACES.spaces ?? []).map((s) => ({ ...s, selected: false })),
        }}
        canManage
        onToggle={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/no spaces chosen, so cairn is reading nothing from google chat/i),
    ).toBeVisible();
  });

  it("filters by search, and says how many of how many matched", async () => {
    render(<SpacePicker spaces={SPACES} canManage onToggle={vi.fn()} />);
    await openSpaces();

    await userEvent.type(screen.getByRole("searchbox", { name: /search spaces/i }), "desi");

    expect(screen.getByRole("checkbox", { name: "Design" })).toBeVisible();
    expect(screen.queryByRole("checkbox", { name: "Platform" })).not.toBeInTheDocument();
    expect(screen.getByText(/1 of 3 spaces match/i)).toBeVisible();
  });

  it("says so when a search matches nothing, without emptying the screen", async () => {
    render(<SpacePicker spaces={SPACES} canManage onToggle={vi.fn()} />);
    await openSpaces();

    await userEvent.type(screen.getByRole("searchbox", { name: /search spaces/i }), "zzz");

    expect(screen.getByText(/no space matches “zzz”/i)).toBeVisible();
  });

  it("says when Google listed no spaces at all, which is not the same as no match", async () => {
    render(
      <SpacePicker spaces={{ spaces: [], notice: SPACE_NOTICE }} canManage onToggle={vi.fn()} />,
    );
    await openSpaces();

    expect(screen.getByText(/google returned no spaces for this account/i)).toBeVisible();
  });

  it("ticks only what the server confirmed, never what was clicked", async () => {
    // **The rule this control exists for.** A refused save must leave the
    // checkbox exactly where it was: a space drawn as selected when the save
    // failed tells somebody CAIRN is reading a room it is not.
    const onToggle = vi.fn();
    render(<SpacePicker spaces={SPACES} canManage onToggle={onToggle} />);
    await openSpaces();

    const design = screen.getByRole("checkbox", { name: "Design" });
    await userEvent.click(design);

    expect(onToggle).toHaveBeenCalledWith("spaces/AAAA2", true);
    // Nothing came back, so nothing moved.
    expect(design).not.toBeChecked();
  });

  it("passes Google's resource name to the caller, never the display name", async () => {
    // Two spaces may share a display name; the resource name is the identity
    // the PUT takes back.
    const onToggle = vi.fn();
    render(<SpacePicker spaces={SPACES} canManage onToggle={onToggle} />);
    await openSpaces();

    await userEvent.click(screen.getByRole("checkbox", { name: "Platform" }));

    expect(onToggle).toHaveBeenCalledWith("spaces/AAAA1", false);
  });

  it("announces a save in flight instead of moving the tick", async () => {
    render(<SpacePicker spaces={SPACES} canManage onToggle={vi.fn()} saving={["spaces/AAAA2"]} />);
    await openSpaces();

    const design = screen.getByRole("checkbox", { name: "Design" });
    expect(design).toBeDisabled();
    expect(design).not.toBeChecked();
    expect(
      screen.getByText(
        /saving your choice\. nothing changes until google and cairn both confirm it/i,
      ),
    ).toBeVisible();
  });

  it("shows an ineligible space as unselectable, with the reason", async () => {
    render(<SpacePicker spaces={SPACES} canManage onToggle={vi.fn()} />);
    await openSpaces();

    const dm = screen.getByRole("checkbox", { name: "Ali and Jo" });
    expect(dm).toBeVisible();
    expect(dm).toBeDisabled();
    expect(screen.getByText(/cairn cannot read this space, so it cannot be chosen/i)).toBeVisible();
    expect(screen.getByText(/does not deliver events for this kind of space/i)).toBeVisible();
  });

  it("admits when Google gave a reason it has no wording for, rather than guessing", async () => {
    render(
      <SpacePicker
        spaces={oneSpace({ eligible: false, selected: false, errorCategory: "SOMETHING_NEW" })}
        canManage
        onToggle={vi.fn()}
      />,
    );
    await openSpaces();

    expect(
      screen.getByText(/google did not give a reason cairn has wording for, so none is shown/i),
    ).toBeVisible();
  });

  it.each([
    ["active", /the subscription is active, so messages from this space are reaching cairn/i],
    ["renewing", /the subscription is renewing/i],
    ["expired", /the subscription expired and was not renewed, so nothing is arriving/i],
    ["suspended", /the subscription is suspended, so nothing is arriving/i],
    ["failed", /the subscription failed, so nothing is arriving/i],
    // The server's own vocabulary, said in the reader's: "error" describes the
    // system's experience and "nothing is arriving" describes theirs.
    ["error", /the subscription failed, so nothing is arriving/i],
    // "We have not asked Google yet" and "we asked and Google has not answered"
    // are different things to be looking at while a feed is empty.
    ["pending", /cairn has asked google to start delivering from this space/i],
    ["deleted", /the subscription has been deleted at google/i],
  ])("says a %s subscription in words, not in a colour", async (state, sentence) => {
    render(
      <SpacePicker spaces={oneSpace({ subscriptionState: state })} canManage onToggle={vi.fn()} />,
    );
    await openSpaces();

    expect(screen.getByText(sentence)).toBeVisible();
  });

  it("does not call a space healthy when the server said nothing about it", async () => {
    // Absent is not fine. A space CAIRN cannot describe is reported as exactly
    // that, rather than rounded up to active.
    render(
      <SpacePicker spaces={oneSpace({ subscriptionState: null })} canManage onToggle={vi.fn()} />,
    );
    await openSpaces();

    expect(screen.getByText(/cairn has not recorded a subscription for this space/i)).toBeVisible();
    expect(
      screen.queryByText(/messages from this space are reaching cairn/i),
    ).not.toBeInTheDocument();
  });

  it("treats a subscription state it does not know as one it cannot describe", async () => {
    render(
      <SpacePicker
        spaces={oneSpace({ subscriptionState: "SUBSCRIPTION_STATE_UNSPECIFIED" })}
        canManage
        onToggle={vi.fn()}
      />,
    );
    await openSpaces();

    expect(screen.getByText(/cairn has not recorded a subscription for this space/i)).toBeVisible();
  });

  it("shows an expiry only when the backend sent one", async () => {
    const { unmount } = render(
      <SpacePicker
        spaces={oneSpace({ subscriptionState: "active", expireTime: "2026-09-01T09:00:00Z" })}
        canManage
        onToggle={vi.fn()}
      />,
    );
    await openSpaces();
    expect(screen.getByText(/renews by/i)).toBeVisible();
    unmount();

    render(
      <SpacePicker
        spaces={oneSpace({ subscriptionState: "active", expireTime: null })}
        canManage
        onToggle={vi.fn()}
      />,
    );
    await openSpaces();
    // No dash, no "unknown": an absent instant is one CAIRN has not recorded.
    expect(screen.queryByText(/renews by/i)).not.toBeInTheDocument();
  });

  it("names why a suspended subscription is failing when it has wording for it", async () => {
    render(
      <SpacePicker
        spaces={oneSpace({ subscriptionState: "suspended", errorCategory: "permission_revoked" })}
        canManage
        onToggle={vi.fn()}
      />,
    );
    await openSpaces();

    expect(
      screen.getByText(/lost access to this space\. reconnecting with an account that can see it/i),
    ).toBeVisible();
  });

  it("says nothing about a subscription for a space nobody chose", async () => {
    // A subscription note against an unselected space sends somebody to fix a
    // problem they do not have.
    render(
      <SpacePicker
        spaces={oneSpace({ selected: false, subscriptionState: "expired" })}
        canManage
        onToggle={vi.fn()}
      />,
    );
    await openSpaces();

    expect(screen.queryByText(/subscription expired/i)).not.toBeInTheDocument();
  });

  it("states the server's own rule and the no-backfill rule where the choosing happens", async () => {
    render(<SpacePicker spaces={SPACES} canManage onToggle={vi.fn()} />);
    await openSpaces();

    expect(screen.getByText(SPACE_NOTICE)).toBeVisible();
    expect(screen.getByText(GOOGLE_CHAT_NO_HISTORY)).toBeVisible();
  });

  it("gives a Member the record read-only, with a sentence naming who changes it", () => {
    render(<SpacePicker spaces={SPACES} canManage={false} />);

    expect(screen.queryByRole("button", { name: /choose spaces/i })).not.toBeInTheDocument();
    expect(
      screen.getByText(/an owner or an admin of this workspace chooses which google chat spaces/i),
    ).toBeVisible();
    // The list itself, not only a count: what CAIRN reads from their workspace
    // is a fact about their own messages.
    expect(screen.getByText("Platform")).toBeVisible();
  });

  it("keeps a read-only reader's list honest about a space that is not delivering", () => {
    render(<SpacePicker spaces={oneSpace({ subscriptionState: "suspended" })} canManage={false} />);

    expect(
      screen.getByText(/the subscription is suspended, so nothing is arriving/i),
    ).toBeVisible();
  });

  it("is operable from the keyboard, and gives focus back when it closes", async () => {
    render(<SpacePicker spaces={SPACES} canManage onToggle={vi.fn()} />);

    const trigger = screen.getByRole("button", { name: /choose spaces/i });
    trigger.focus();
    await userEvent.keyboard("{Enter}");

    // Opening puts the reader where they wanted to be typing, not at the top of
    // a list of checkboxes they have to tab through.
    expect(screen.getByRole("searchbox", { name: /search spaces/i })).toHaveFocus();

    await userEvent.click(screen.getByRole("button", { name: /done choosing spaces/i }));

    // Live node, not a stale one: React has just re-mounted the trigger.
    expect(screen.getByRole("button", { name: /choose spaces/i })).toHaveFocus();
  });

  it("shows a refused save next to the control that was pressed", () => {
    render(
      <SpacePicker
        spaces={SPACES}
        canManage
        onToggle={vi.fn()}
        problem={{ message: "CAIRN could not save that space choice." }}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/could not save that space choice/i);
  });

  it("announces the skeleton rather than leaving it silent", () => {
    render(<SpacePickerLoading />);

    expect(screen.getByRole("status")).toHaveTextContent(/loading the google chat spaces/i);
  });

  it("passes an axe audit with the picker open", async () => {
    const { container } = render(<SpacePicker spaces={SPACES} canManage onToggle={vi.fn()} />);
    await openSpaces();

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("passes an axe audit read-only, with a failure showing", async () => {
    const { container } = render(
      <SpacePicker
        spaces={SPACES}
        canManage={false}
        problem={{ message: "CAIRN could not save that space choice." }}
      />,
    );

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

/**
 * Folding the save's answer back onto the list.
 *
 * `PUT` answers with resource names and no display names, so this is the single
 * place a confirmation becomes a tick. Getting it wrong in either direction is a
 * false statement about what CAIRN is reading.
 */
describe("reconcileSpaces", () => {
  const LIST: GoogleChatSpaceList = {
    spaces: [
      {
        name: "spaces/AAAA1",
        displayName: "Platform",
        eligible: true,
        selected: true,
        subscriptionState: "active",
        expireTime: null,
        errorCategory: null,
      },
      {
        name: "spaces/AAAA2",
        displayName: "Design",
        eligible: true,
        selected: false,
        subscriptionState: null,
        expireTime: null,
        errorCategory: null,
      },
    ],
    notice: "The old sentence.",
  };

  it("ticks exactly what the server confirmed and unticks everything else", () => {
    const next = reconcileSpaces(LIST, {
      spaceNames: ["spaces/AAAA2"],
      notice: "The current sentence.",
    });

    expect((next.spaces ?? []).map((space) => [space.name, space.selected])).toEqual([
      ["spaces/AAAA1", false],
      ["spaces/AAAA2", true],
    ]);
  });

  it("keeps everything else the GET described, including the subscription state", () => {
    const next = reconcileSpaces(LIST, { spaceNames: ["spaces/AAAA1"], notice: "Current." });

    expect(next.spaces?.[0]?.displayName).toBe("Platform");
    expect(next.spaces?.[0]?.subscriptionState).toBe("active");
  });

  it("takes the notice from the response that is now current", () => {
    // Keeping the older list's sentence here would be the one place the client
    // and the server could come to disagree about the standing rule.
    const next = reconcileSpaces(LIST, { spaceNames: [], notice: "The current sentence." });

    expect(next.notice).toBe("The current sentence.");
  });
});
