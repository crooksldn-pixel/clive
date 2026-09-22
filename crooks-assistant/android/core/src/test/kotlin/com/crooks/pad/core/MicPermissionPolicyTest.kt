package com.crooks.pad.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MicPermissionPolicyTest {

    private val CROOKS = "https://crooks-assistant.taildfb357.ts.net"
    private val policy = MicPermissionPolicy(OriginAllowList.of(CROOKS))

    private fun request(
        origin: String? = CROOKS,
        resources: Set<MediaResource> = setOf(MediaResource.AUDIO_CAPTURE),
        os: OsMicPermission = OsMicPermission.GRANTED,
    ) = MicRequest(origin, resources, os)

    @Test fun `the trusted origin with the OS permission gets the microphone`() {
        assertEquals(MicDecision.GRANT, policy.decide(request()).decision)
    }

    @Test fun `an untrusted origin is refused silently`() {
        // Silently to the OWNER, loudly in telemetry. Showing a microphone explanation here
        // would teach the owner to grant a microphone to whatever asked.
        for (origin in listOf("https://evil.example", "http://crooks-assistant.taildfb357.ts.net", "null", "", null)) {
            val outcome = policy.decide(request(origin = origin))
            assertEquals("$origin must not get the microphone", MicDecision.DENY_SILENT, outcome.decision)
            assertEquals("untrusted_origin", outcome.reason)
        }
    }

    @Test fun `the camera is never granted, even to CROOKS`() {
        // The web layer never asks. A shell that WOULD grant it if asked is a shell with a
        // camera in a workroom, and the request itself is worth recording.
        assertEquals(
            MicDecision.DENY_SILENT,
            policy.decide(request(resources = setOf(MediaResource.VIDEO_CAPTURE))).decision,
        )
        assertEquals(
            "asking for both must not smuggle the camera through on the microphone's ticket",
            MicDecision.DENY_SILENT,
            policy.decide(request(resources = setOf(MediaResource.AUDIO_CAPTURE, MediaResource.VIDEO_CAPTURE))).decision,
        )
    }

    @Test fun `a protected media identifier is a device id by another name`() {
        assertEquals(
            MicDecision.DENY_SILENT,
            policy.decide(request(resources = setOf(MediaResource.PROTECTED_MEDIA_ID))).decision,
        )
    }

    @Test fun `Android refusing the microphone produces a CROOKS explanation, not silence`() {
        // §8: denial must produce a CROOKS-native explanation. The two OS denials differ in
        // what the owner can do next, and the card differs with them — but neither is silent.
        val canAsk = policy.decide(request(os = OsMicPermission.DENIED_CAN_ASK))
        assertEquals(MicDecision.DENY_EXPLAIN, canAsk.decision)
        assertEquals("os_denied_can_ask", canAsk.reason)

        val never = policy.decide(request(os = OsMicPermission.DENIED_PERMANENTLY))
        assertEquals(MicDecision.DENY_EXPLAIN, never.decision)
        assertEquals("os_denied_permanently", never.reason)
    }

    @Test fun `only the microphone is ever handed back, never what was asked for`() {
        // The usual shape of this bug is `request.grant(request.resources)` once the decision
        // is yes. The granted set is fixed and does not consult the request at all.
        val granted = policy.grantedResources()
        assertEquals(setOf(MediaResource.AUDIO_CAPTURE), granted)
        assertTrue(MediaResource.AUDIO_CAPTURE in granted)
        assertFalse(MediaResource.VIDEO_CAPTURE in granted)
        assertFalse(MediaResource.MIDI_SYSEX in granted)
        assertFalse(MediaResource.PROTECTED_MEDIA_ID in granted)
    }

    @Test fun `a request for nothing we recognise is refused`() {
        assertEquals(MicDecision.DENY_SILENT, policy.decide(request(resources = emptySet())).decision)
        assertEquals(MicDecision.DENY_SILENT, policy.decide(request(resources = setOf(MediaResource.OTHER))).decision)
    }
}

class ShellVisibilityTest {

    /**
     * §7, structurally.
     *
     * In Phase 4, sixty-three ordinary control taps became voice recordings because a
     * transparent full-viewport surface sat over the controls. In the native shell the same
     * mistake — a recovery view left INVISIBLE or at alpha 0 instead of GONE — would sit above
     * the WebView and swallow every touch in the product, and the pad would simply look
     * frozen.
     *
     * The defence is that the shell cannot EXPRESS two layers at once. [ShellVisibility]
     * returns one [ShellLayer]; there is no set, no pair of booleans, no z-order to get wrong.
     * These tests hold that shape: every combination of state and admin produces exactly one
     * layer, and WEB is produced for exactly one state.
     */
    @Test fun `exactly one layer is ever on screen`() {
        for (state in PadState.entries) {
            for (admin in listOf(true, false)) {
                for (connected in listOf(true, false)) {
                    val layer = ShellVisibility.layerFor(state, admin, connected)
                    assertTrue("every combination must name a layer", layer in ShellLayer.entries)
                }
            }
        }
    }

    @Test fun `the web layer is shown for ONLINE and for nothing else`() {
        for (state in PadState.entries) {
            val layer = ShellVisibility.layerFor(state, adminOpen = false, hasEverConnected = true)
            if (state == PadState.ONLINE) assertEquals(ShellLayer.WEB, layer)
            else assertFalse("$state must not show the workspace", layer == ShellLayer.WEB)
        }
    }

    @Test fun `nothing is ever drawn over a healthy workspace`() {
        // §19: when healthy, the shell disappears. Not "fades", not "shows a small badge".
        assertEquals(ShellLayer.WEB, ShellVisibility.layerFor(PadState.ONLINE, false, true))
        assertEquals(ShellLayer.WEB, ShellVisibility.layerFor(PadState.ONLINE, false, false))
    }

    @Test fun `admin is the only thing that may cover a working workspace`() {
        // And it is deliberate and modal: the owner asked for it with a six-press gesture and
        // a PIN, so it is not an accident and it is not a surprise.
        assertEquals(ShellLayer.ADMIN, ShellVisibility.layerFor(PadState.ONLINE, adminOpen = true, hasEverConnected = true))
        for (state in PadState.entries) {
            assertEquals(ShellLayer.ADMIN, ShellVisibility.layerFor(state, true, true))
        }
    }

    @Test fun `the launch path is for the first connection and the recovery card thereafter`() {
        // "Starting CROOKS OS…" is reassuring the first time and a lie the fourth.
        assertEquals(ShellLayer.LAUNCH, ShellVisibility.layerFor(PadState.CONNECTING, false, hasEverConnected = false))
        assertEquals(ShellLayer.RECOVERY, ShellVisibility.layerFor(PadState.CONNECTING, false, hasEverConnected = true))
        assertEquals(ShellLayer.LAUNCH, ShellVisibility.layerFor(PadState.CROOKS_OS_STARTING, false, false))
        assertEquals(ShellLayer.RECOVERY, ShellVisibility.layerFor(PadState.CROOKS_OS_STARTING, false, true))
    }

    @Test fun `a refused microphone covers a healthy workspace, and closes again`() {
        // §8 against §19. A refused getUserMedia is invisible from inside the document — the
        // owner holds the orb, speaks, and NOTHING happens — so if the shell stays hidden the
        // product's answer to "CROOKS cannot hear me" is silence. This is the one case where
        // the shell covers a working workspace uninvited.
        assertEquals(
            ShellLayer.RECOVERY,
            ShellVisibility.layerFor(PadState.ONLINE, adminOpen = false, hasEverConnected = true, micExplanationPending = true),
        )
        // And dismissing it goes straight back to the workspace, so the owner is never locked
        // out of a perfectly good CROOKS by a permission they can live without this afternoon.
        assertEquals(
            ShellLayer.WEB,
            ShellVisibility.layerFor(PadState.ONLINE, adminOpen = false, hasEverConnected = true, micExplanationPending = false),
        )
    }

    @Test fun `admin and diagnostics both outrank the microphone card`() {
        assertEquals(
            ShellLayer.ADMIN,
            ShellVisibility.layerFor(PadState.ONLINE, adminOpen = true, hasEverConnected = true, micExplanationPending = true),
        )
        assertEquals(
            ShellLayer.DIAGNOSTICS,
            ShellVisibility.layerFor(PadState.ONLINE, adminOpen = false, hasEverConnected = true, diagnosticsOpen = true, micExplanationPending = true),
        )
    }

    @Test fun `diagnostics is reachable from every state without a PIN`() {
        // The one screen that explains why nothing works must not be behind the thing that is
        // not working.
        for (state in PadState.entries) {
            assertEquals(
                ShellLayer.DIAGNOSTICS,
                ShellVisibility.layerFor(state, adminOpen = false, hasEverConnected = true, diagnosticsOpen = true),
            )
        }
    }

    @Test fun `admin outranks diagnostics, so a state change cannot throw someone out mid-PIN`() {
        assertEquals(
            ShellLayer.ADMIN,
            ShellVisibility.layerFor(PadState.MAC_OFFLINE, adminOpen = true, hasEverConnected = true, diagnosticsOpen = true),
        )
    }

    @Test fun `a failure state is a card even on the very first launch`() {
        // A brand-new tablet whose Mac is off must say "CROOKS Mac is off", not sit on a
        // wordmark. The launch path is for hope, not for a known failure.
        for (state in listOf(PadState.MAC_OFFLINE, PadState.NETWORK_OFFLINE, PadState.CROOKS_OS_UNHEALTHY, PadState.APP_ERROR)) {
            assertEquals(ShellLayer.RECOVERY, ShellVisibility.layerFor(state, false, hasEverConnected = false))
        }
    }
}
