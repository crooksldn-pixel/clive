package com.crooks.pad.core

/**
 * CROOKS Pad — who may switch the microphone on.
 *
 * §6.4 requires that `onPermissionRequest` check the origin, and the requirement is not
 * ceremonial. The default implementation of that callback in a naive WebView shell is
 * `request.grant(request.resources)` — grant whatever was asked for, to whoever asked. In a
 * shell that only ever shows one origin that looks harmless, right up to the moment a
 * navigation guard is loosened, a redirect is followed, or an iframe is added to the page: at
 * that point some other origin is holding a live microphone in a room where the owner talks
 * about the business all day, and nothing on screen says so.
 *
 * So the decision is made here, from four facts, and it grants exactly one resource to
 * exactly one origin.
 *
 * ON THE SHAPE OF THE ANSWER. A denial that the owner cannot see is the failure §8 names:
 * "denial produces a CROOKS-native explanation, not silent failure". But there are two kinds
 * of denial and they must not share a screen. A denial because ANDROID has not given the app
 * the microphone is the owner's problem and deserves a card with a button. A denial because
 * an UNTRUSTED origin asked is not the owner's problem at all — it is a security event, and
 * showing the owner a microphone explanation for it would train them to grant it. That one is
 * silent to the owner and loud in telemetry.
 */

enum class MicDecision {
    /** Grant audio capture, and only audio capture, to the trusted origin. */
    GRANT,

    /**
     * Deny, and show the owner a CROOKS card explaining that the microphone is switched off
     * for CROOKS, with the one action that fixes it.
     */
    DENY_EXPLAIN,

    /**
     * Deny, show the owner nothing, record `pad_mic_permission` with the reason. Used when an
     * untrusted origin asks, and when something other than the microphone is asked for.
     */
    DENY_SILENT,
}

/** What a WebView permission request can ask for, reduced to what the shell cares about. */
enum class MediaResource { AUDIO_CAPTURE, VIDEO_CAPTURE, MIDI_SYSEX, PROTECTED_MEDIA_ID, OTHER }

/** Whether Android itself has given this app the microphone. */
enum class OsMicPermission {
    GRANTED,

    /** Not granted, and the owner can still be asked. */
    DENIED_CAN_ASK,

    /** Not granted, and Android will no longer show the prompt: "don't ask again", or policy. */
    DENIED_PERMANENTLY,
}

data class MicRequest(
    val origin: String?,
    val resources: Set<MediaResource>,
    val osPermission: OsMicPermission,
)

data class MicOutcome(val decision: MicDecision, val reason: String)

class MicPermissionPolicy(private val allowList: OriginAllowList) {

    fun decide(request: MicRequest): MicOutcome {
        if (!allowList.allowsOriginString(request.origin)) {
            return MicOutcome(MicDecision.DENY_SILENT, "untrusted_origin")
        }
        // The camera is never granted. The pad has one, the web layer never asks for it, and
        // a shell that would grant it if asked is a shell with a camera in a workroom. Asking
        // for it at all is worth recording.
        if (MediaResource.VIDEO_CAPTURE in request.resources) {
            return MicOutcome(MicDecision.DENY_SILENT, "video_never_granted")
        }
        if (MediaResource.PROTECTED_MEDIA_ID in request.resources) {
            // A device identifier by another name. Never.
            return MicOutcome(MicDecision.DENY_SILENT, "device_id_never_granted")
        }
        if (MediaResource.AUDIO_CAPTURE !in request.resources) {
            return MicOutcome(MicDecision.DENY_SILENT, "not_audio")
        }
        return when (request.osPermission) {
            OsMicPermission.GRANTED -> MicOutcome(MicDecision.GRANT, "trusted_origin_audio")
            OsMicPermission.DENIED_CAN_ASK -> MicOutcome(MicDecision.DENY_EXPLAIN, "os_denied_can_ask")
            OsMicPermission.DENIED_PERMANENTLY -> MicOutcome(MicDecision.DENY_EXPLAIN, "os_denied_permanently")
        }
    }

    /**
     * Only the resources that were actually granted are handed back to the WebView. The
     * temptation is to pass `request.resources` straight through once the decision is GRANT;
     * that would grant the camera along with the microphone to any page that asked for both,
     * which is how this class of bug is usually shipped.
     */
    fun grantedResources(): Set<MediaResource> = setOf(MediaResource.AUDIO_CAPTURE)
}
