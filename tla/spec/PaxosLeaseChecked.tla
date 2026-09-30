---- MODULE PaxosLeaseChecked ----
(***************************************************************************)
(* PaxosLease together with the assumptions under which it is safe.        *)
(* Safe configurations point TLC at this module.  Configurations that       *)
(* intentionally violate the quarantine bound point at PaxosLease.tla       *)
(* directly, so that TLC exhibits the resulting lease-exclusivity           *)
(* violation instead of rejecting the configuration.                        *)
(*                                                                          *)
(* With A2's refusal, the quarantine bound tracks the proposer attempt     *)
(* duration, not the acceptor exclusion duration: a forgotten accepted      *)
(* lease supports an attempt whose Prepare preceded the crash, and that     *)
(* attempt is unusable ProposerDuration later, while a forgotten promise    *)
(* imposes no bound of its own.  Quarantine >= AcceptorDuration is         *)
(* NOT required: see PaxosLeaseQuarantineEqualsProposer.cfg, which passes   *)
(* with Quarantine = ProposerDuration < AcceptorDuration.                   *)
(***************************************************************************)
EXTENDS PaxosLease

ASSUME Quarantine >= ProposerDuration

(* A2 includes the acceptor-side refusal: an acceptor never replaces a live *)
(* lease of a different owner.  Configurations of the overwriting rule of   *)
(* [1] and of the audited implementations point at PaxosLease.tla.          *)
ASSUME RefuseLiveOverwrite

====
