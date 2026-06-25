from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "labview_manifest.json"
PORTS_PATH = ROOT / "src" / "thermo_acoustic" / "labview_ports.py"
STATUS_PATH = ROOT / "port_status.json"
TBD_PATH = ROOT / "docs" / "PORTING_TBD.md"


RUNTIME_TBD = [
    (
        "Hamamatsu real camera validation",
        "Run `tools/test_hamamatsu_camera.py` against the connected camera and verify "
        "open, exposure, ROI/subarray, snapshot, sequence capture, software trigger, "
        "and cleanup behavior.",
    ),
    (
        "Camera image handling",
        "Verify that the Python TIFF output matches the LabVIEW image output needs, "
        "including bit depth, frame naming, metadata, and any TDMS sidecar data expected "
        "by downstream analysis.",
    ),
    (
        "Camera UI preview",
        "Add a live/snapshot image display in the Camera tab if the operator needs the "
        "Python UI to replace LabVIEW's image window behavior.",
    ),
    (
        "Cetoni/Qmix real pump backend",
        "The Qmix/Cetoni backend is implemented through `QmixPumpBackend`, but it still "
        "needs to be validated with the installed Qmix/Cetoni stack, real syringe "
        "geometry, safe flow limits, and the user's device configuration.",
    ),
    (
        "Valve serial validation",
        "Confirm real valve commands, baud rate, line endings, and response parsing on "
        "the connected MX valve hardware.",
    ),
    (
        "Analog Discovery MSO hardware validation",
        "Exercise all MSO trigger source options on the real AD2/AD3 hardware and check "
        "that channel enable, sample rate, duration, x-axis scale, and y-axis scale match "
        "the physical oscilloscope signal.",
    ),
    (
        "End-to-end experiment execution",
        "Run the Experiment tab with the real AD2, Hamamatsu camera, pump, and valve "
        "together, then compare folder output, saved settings, image data, trigger timing, "
        "flush timing, abort cleanup, and status messages against the LabVIEW behavior.",
    ),
    (
        "Packaging and operator startup",
        "Decide whether the final app should be launched from source, a shortcut, or a "
        "packaged executable, then document the required SDK/runtime installations.",
    ),
]


IMPLEMENTED = {
    "Main.vi",
    "Application.lvclass:Application_Init.vi",
    "Application.lvclass:CleanUp.vi",
    "Application.lvclass:CreateQueues.vi",
    "Application.lvclass:CreateStopEvent.vi",
    "Application.lvclass:CreateUIEvent.vi",
    "Application.lvclass:DeQueueMain.vi",
    "Application.lvclass:EnqueueMain.vi",
    "Application.lvclass:FireStatusEvent.vi",
    "Application.lvclass:FireStopEvent.vi",
    "Application.lvclass:FireUIEvent.vi",
    "Application.lvclass:Flush.vi",
    "Application.lvclass:FlushMainQueue.vi",
    "Application.lvclass:ListenAbort.vi",
    "Application.lvclass:PeekQueueMain.vi",
    "Application.lvclass:RegisterEvents.vi",
    "Application.lvclass:RunExperiment2.vi",
    "Application.lvclass:Wait.vi",
    "Application.lvclass:waitforpump.vi",
    "Application.lvclass:GetAD2_SDK.vi",
    "Application.lvclass:SetAD2_SDK.vi",
    "Application.lvclass:GetCetoniPump.vi",
    "Application.lvclass:SetCetoniPump.vi",
    "Application.lvclass:GetExperimentSeriesGeneral.vi",
    "Application.lvclass:SetExperimentSeriesGeneral.vi",
    "Application.lvclass:GetHamamatsu.vi",
    "Application.lvclass:SetHamamatsu.vi",
    "Application.lvclass:GetPrior_Zmotor.vi",
    "Application.lvclass:SetPrior_Zmotor.vi",
    "Application.lvclass:GetValve.vi",
    "Application.lvclass:SetValve.vi",
    "Application.lvclass:CheckLoopError.vi",
    "Application.lvclass:ErrorHandlerEventLoop.vi",
    "Application.lvclass:ErrorHandlerMainLoop.vi",
    "Application.lvclass:ZStack.vi",
    "Application Directory.vi",
    "subElapsedTime.vi",
    "FormatTime String.vi",
    "Check if File or Folder Exists.vi",
    "Trim Whitespace One-Sided.vi",
    "Trim Whitespace.vi",
    "Search and Replace Pattern.vi",
    "Find Tag.vi",
    "Format Message String.vi",
    "Error Cluster From Error Code.vi",
    "Clear Errors.vi",
    "BuildHelpPath.vi",
    "Check Special Tags.vi",
    "Convert property node font to graphics font.vi",
    "Details Display Dialog.vi",
    "Error Code Database.vi",
    "ex_CorrectErrorChain.vi",
    "General Error Handler.vi",
    "General Error Handler Core CORE.vi",
    "GetHelpDir.vi",
    "GetRTHostConnectedProp.vi",
    "Get String Text Bounds.vi",
    "Get Text Rect.vi",
    "Longest Line Length in Pixels.vi",
    "Not Found Dialog.vi",
    "Set Bold Text.vi",
    "Set String Value.vi",
    "Simple Error Handler.vi",
    "subFile Dialog.vi",
    "Three Button Dialog.vi",
    "Three Button Dialog CORE.vi",
    "CetoniPump.lvclass:CetoniPump_Init.vi",
    "CetoniPump.lvclass:CleanUp.vi",
    "CetoniPump.lvclass:ConfigureFlowUnit.vi",
    "CetoniPump.lvclass:ConfigureSyringe.vi",
    "CetoniPump.lvclass:ConfigureSyringeBD.vi",
    "CetoniPump.lvclass:Empty.vi",
    "CetoniPump.lvclass:GenerateFlow.vi",
    "CetoniPump.lvclass:ReadStatus.vi",
    "CetoniPump.lvclass:ReferenceMove.vi",
    "CetoniPump.lvclass:Refill.vi",
    "CetoniPump.lvclass:SetFillLevel.vi",
    "CetoniPump.lvclass:Stop.vi",
    "ExperimentSeries2.lvclass:Deque experiment.vi",
    "ExperimentSeries2.lvclass:EnqueExperiments.vi",
    "ExperimentSeries2.lvclass:ExperimentSeries2_Init.vi",
    "ExperimentSeries2.lvclass:CreateExperiments.vi",
    "ExperimentSeries2.lvclass:GetSreiesPath.vi",
    "ExperimentSeries2.lvclass:See Elements Left.vi",
    "Experiment2.lvclass:CleanUp.vi",
    "Experiment2.lvclass:CreatefolderandTDMS.vi",
    "Experiment2.lvclass:Experiment2_Init.vi",
    "Experiment2.lvclass:GetClockSettings.vi",
    "Experiment2.lvclass:GetExperimentFolder.vi",
    "Experiment2.lvclass:GetFlushSettings.vi",
    "Experiment2.lvclass:GetGlobalExposure.vi",
    "Experiment2.lvclass:GetSequenceSettings.vi",
    "Experiment2.lvclass:GetWFGConfig.vi",
    "Experiment2.lvclass:SaveCameraSettings.vi",
    "Experiment2.lvclass:SaveImageData.vi",
    "Experiment2.lvclass:SaveSettings.vi",
    "Cetoni_Simulated.lvclass:CleanUp.vi",
    "Cetoni_Simulated.lvclass:Cetoni_Simulated_Init.vi",
    "Cetoni_Simulated.lvclass:ConfigureFlowUnit.vi",
    "Cetoni_Simulated.lvclass:ConfigureSyringe.vi",
    "Cetoni_Simulated.lvclass:ConfigureSyringeBD.vi",
    "Cetoni_Simulated.lvclass:Empty.vi",
    "Cetoni_Simulated.lvclass:GenerateFlow.vi",
    "Cetoni_Simulated.lvclass:ReadStatus.vi",
    "Cetoni_Simulated.lvclass:ReferenceMove.vi",
    "Cetoni_Simulated.lvclass:Refill.vi",
    "Cetoni_Simulated.lvclass:SetFillLevel.vi",
    "Cetoni_Simulated.lvclass:Stop.vi",
    "Hamamatsu_simulated.lvclass:CaptureSnapshot.vi",
    "Hamamatsu_simulated.lvclass:CenterROI.vi",
    "Hamamatsu_simulated.lvclass:CleanUp.vi",
    "Hamamatsu_simulated.lvclass:ConfigureExposureTime.vi",
    "Hamamatsu_simulated.lvclass:ConfigureROI.vi",
    "Hamamatsu_simulated.lvclass:ConfigureSequence.vi",
    "Hamamatsu_simulated.lvclass:ConfigureSnapshot.vi",
    "Hamamatsu_simulated.lvclass:GetCameraBufferSize.vi",
    "Hamamatsu_simulated.lvclass:GetHandleOut.vi",
    "Hamamatsu_simulated.lvclass:GetSubRegion.vi",
    "Hamamatsu_simulated.lvclass:Hamamatsu_simulated_Init.vi",
    "Hamamatsu_simulated.lvclass:ImageSequence.vi",
    "Hamamatsu_simulated.lvclass:OpenCamera.vi",
    "Hamamatsu_simulated.lvclass:ReadReadoutTime.vi",
    "Hamamatsu_simulated.lvclass:ReadSubregionLimitsandValue.vi",
    "Hamamatsu_simulated.lvclass:saveSequence.vi",
    "Hamamatsu_simulated.lvclass:StartCapture.vi",
    "Hamamatsu_simulated.lvclass:StopCapture.vi",
    "Hamamatsu_simulated.lvclass:SWTrigg.vi",
    "Hamamatsu_simulated.lvclass:UpdateRoiLimits.vi",
    "Prior_Zmotor.lvclass:CleanUp.vi",
    "Prior_Zmotor.lvclass:Prior_Zmotor_Init.vi",
    "Prior_Zmotor.lvclass:ReadPosition.vi",
    "Prior_Zmotor.lvclass:readmovement.vi",
    "Prior_Zmotor.lvclass:ZeroPos.vi",
    "Valve_Sim.lvclass:CleanUp.vi",
    "Valve_Sim.lvclass:Valve_Sim_Init.vi",
    "Valve_Sim.lvclass:ValvePos1.vi",
    "Valve_Sim.lvclass:ValvePos2.vi",
    "AD2_DO_SDK.lvclass:AD2_DO_SDK_Init.vi",
    "AD2_DO_SDK.lvclass:DOConfigTrigger.vi",
    "AD2_DO_SDK.lvclass:DOConfigure.vi",
    "AD2_DO_SDK.lvclass:DOConfigureClock_Speziale.vi",
    "AD2_DO_SDK.lvclass:DOConfigureCustomaPattern.vi",
    "AD2_DO_SDK.lvclass:DOConfigureIdle.vi",
    "AD2_DO_SDK.lvclass:DOCustomData.ctl",
    "AD2_DO_SDK.lvclass:DOCustomPatternBuildArray.vi",
    "AD2_DO_SDK.lvclass:DODividerConfig.vi",
    "AD2_DO_SDK.lvclass:DOEnableSet.vi",
    "AD2_DO_SDK.lvclass:DOReset.vi",
    "AD2_DO_SDK.lvclass:DOSingleCh.ctl",
    "AD2_DO_SDK.lvclass:DOTrigger.ctl",
    "AD2_DO_SDK.lvclass:DOTYpeConfig.vi",
    "AD2_DO_SDK.lvclass:GetPhdwf.vi",
    "AD2_DO_SDK.lvclass:StartStopDO.vi",
    "AD2_WFG_SDK.lvclass:AD2_WFG_SDK_Init.vi",
    "AD2_WFG_SDK.lvclass:GetPhdwf.vi",
    "AD2_WFG_SDK.lvclass:GetWFGConfig.vi",
    "AD2_WFG_SDK.lvclass:SetWFGConfig.vi",
    "AD2_WFG_SDK.lvclass:WFG.ctl",
    "AD2_WFG_SDK.lvclass:WFGCh.ctl",
    "AD2_WFG_SDK.lvclass:WFGCheckConfigValid.vi",
    "AD2_WFG_SDK.lvclass:WFGConfigure.vi",
    "AD2_WFG_SDK.lvclass:WFGConfigureCarrierSingleCh.vi",
    "AD2_WFG_SDK.lvclass:WFGConfigureFMMODSingleCh.vi",
    "AD2_WFG_SDK.lvclass:WFGConfigureReadBack.vi",
    "AD2_WFG_SDK.lvclass:WFGConfigureSingleCh.vi",
    "AD2_WFG_SDK.lvclass:WFGConfigureTriggerSingleCh.vi",
    "AD2_WFG_SDK.lvclass:WFGDynamicConfigCh.vi",
    "AD2_WFG_SDK.lvclass:WFGStartStopAllCh.vi",
    "AD2_MSO_SDK.lvclass:AD2_MSO_SDK_Init.vi",
    "AD2_SDK.lvclass:AD2TriggerSources.ctl",
    "AD2_SDK.lvclass:AD2_SDK_Init.vi",
    "AD2_SDK.lvclass:CleanUp.vi",
    "AD2_SDK.lvclass:ConfigDOClockSpezial.vi",
    "AD2_SDK.lvclass:ConfigDOCustom.vi",
    "AD2_SDK.lvclass:ConfigWFG.vi",
    "AD2_SDK.lvclass:GetPhdwf.vi",
    "AD2_SDK.lvclass:OpenAndUseFirstDevice.vi",
    "AD2_SDK.lvclass:PCTrig.vi",
    "DOConfigureCustomData.ctl",
    "Olasdwf.lvlib:Error Converter (ErrCode or Status).vi",
    "Olasdwf.lvlib:F Dwf Analog Out Configure.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Idle Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Master Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Amplitude Get.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Amplitude Info.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Amplitude Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Enable Get.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Enable Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Frequency Get.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Frequency Info.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Frequency Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Function Get.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Function Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Offset Get.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Offset Info.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Offset Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Phase Get.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Phase Info.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Phase Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Symmetry Get.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Symmetry Info.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Node Symmetry Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Repeat Get.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Repeat Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Repeat Trigger Get.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Repeat Trigger Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Run Get.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Run Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Trigger Source Get.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Trigger Source Set.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Wait Get.vi",
    "Olasdwf.lvlib:F Dwf Analog Out Wait Set.vi",
    "Olasdwf.lvlib:F Dwf Device Auto Configure Set.vi",
    "Olasdwf.lvlib:F Dwf Device Close.vi",
    "Olasdwf.lvlib:F Dwf Device Close All.vi",
    "Olasdwf.lvlib:F Dwf Device Open.vi",
    "Olasdwf.lvlib:F Dwf Device Reset.vi",
    "Olasdwf.lvlib:F Dwf Device Trigger PC.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Configure.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Count.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Counter Init Set.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Counter Set.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Data Info.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Data Set.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Divider Info.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Divider Set.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Enable Set.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Idle Set.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Internal Clock Info.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Repeat Set.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Repeat Trigger Set.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Reset.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Run Set.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Trigger Source Set.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Type Set.vi",
    "Olasdwf.lvlib:F Dwf Digital Out Wait Set.vi",
    "Olasdwf.lvlib:F Dwf Enum.vi",
    "Olasdwf.lvlib:F Dwf Enum Device Is Opened.vi",
    "Olasdwf.lvlib:F Dwf Enum Device Name.vi",
    "Olasdwf.lvlib:F Dwf Enum SN.vi",
    "Olasdwf.lvlib:F Dwf Get Last Error.vi",
    "Olasdwf.lvlib:F Dwf Get Last Error Msg.vi",
    "NI_FileType.lvlib:FT_FileTypes.ctl",
    "NI_FileType.lvlib:Get File Type.vi",
    "NI_FileType.lvlib:Is File an LLB.vi",
    "NI_FileType.lvlib:LVFileType.ctl",
    "NI_PackedLibraryUtility.lvlib:Get Exported File List.vi",
    "Hamamatsu.lvclass:CaptureSnapshot.vi",
    "Hamamatsu.lvclass:CenterROI.vi",
    "Hamamatsu.lvclass:CleanUp.vi",
    "Hamamatsu.lvclass:ConfigureExposureTime.vi",
    "Hamamatsu.lvclass:ConfigureROI.vi",
    "Hamamatsu.lvclass:ConfigureSequence.vi",
    "Hamamatsu.lvclass:ConfigureSnapshot.vi",
    "Hamamatsu.lvclass:GetCameraBufferSize.vi",
    "Hamamatsu.lvclass:GetHandleOut.vi",
    "Hamamatsu.lvclass:GetSubRegion.vi",
    "Hamamatsu.lvclass:Hamamatsu_Init.vi",
    "Hamamatsu.lvclass:ImageSequence.vi",
    "Hamamatsu.lvclass:OpenCamera.vi",
    "Hamamatsu.lvclass:ReadReadoutTime.vi",
    "Hamamatsu.lvclass:ReadSubregionLimitsandValue.vi",
    "Hamamatsu.lvclass:saveSequence.vi",
    "Hamamatsu.lvclass:StartCapture.vi",
    "Hamamatsu.lvclass:StopCapture.vi",
    "Hamamatsu.lvclass:SWTrigg.vi",
    "Hamamatsu.lvclass:UpdateRoiLimits.vi",
    "Controlling_the_Pump_Reglo_D.ctl",
    "DialogType.ctl",
    "DialogTypeEnum.ctl",
    "ErrWarn.ctl",
    "eventvkey.ctl",
    "hamamatsushowseq.vi",
    "Image Type",
    "IMAQ ArrayToImage",
    "IMAQ Copy",
    "IMAQ Create",
    "IMAQ Dispose",
    "IMAQ Image.ctl",
    "IMAQ WindClose",
    "IMAQ WindDisplayMapping",
    "IMAQ WindDraw",
    "IMAQ WindZoom 2",
    "IMAQ Write BMP File 2",
    "IMAQ Write File 2",
    "IMAQ Write Image And Vision Info File 2",
    "IMAQ Write JPEG File 2",
    "IMAQ Write JPEG2000 File 2",
    "IMAQ Write PNG File 2",
    "IMAQ Write TIFF File 2",
    "LVBoundsTypeDef.ctl",
    "LVMinMaxIncTypeDef.ctl",
    "LVRectTypeDef.ctl",
    "TagReturnType.ctl",
    "VISA Configure Serial Port",
    "VISA Configure Serial Port (Instr).vi",
    "VISA Configure Serial Port (Serial Instr).vi",
    "whitespace.ctl",
    "Prior_Zmotor.lvclass:GoToAbsPos.vi",
    "Valve.lvclass:CleanUp.vi",
    "Valve.lvclass:Valve_Init.vi",
    "Valve.lvclass:ValvePos1.vi",
    "Valve.lvclass:ValvePos2.vi",
    "Hamamatsu.lvclass:SubRegion.ctl",
    "Hamamatsu.lvclass:SubRegionLimits.ctl",
}

PARTIAL = {
    "Hamamatsu_simulated.lvclass:ConfigureSequence.vi",
    "Hamamatsu_simulated.lvclass:GetCameraBufferSize.vi",
    "Hamamatsu_simulated.lvclass:GetSubRegion.vi",
    "Hamamatsu_simulated.lvclass:ImageSequence.vi",
    "Hamamatsu_simulated.lvclass:ReadReadoutTime.vi",
    "Hamamatsu_simulated.lvclass:StartCapture.vi",
    "Hamamatsu_simulated.lvclass:StopCapture.vi",
    "Hamamatsu_simulated.lvclass:saveSequence.vi",
}


@dataclass(frozen=True)
class PortEntry:
    vi_name: str
    python_name: str
    module: str
    status: str
    source_path: str | None
    images: list[str]


def _python_name(vi_name: str) -> str:
    text = vi_name.replace(".lvclass:", "_").replace(".lvlib:", "_")
    text = re.sub(r"\.vi$", "", text)
    text = re.sub(r"\.ctl$", "", text)
    text = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower()
    if not text or text[0].isdigit():
        text = f"vi_{text}"
    return text


def _module_name(vi_name: str) -> str:
    if ":" in vi_name:
        return vi_name.split(":", 1)[0]
    if vi_name.endswith(".vi"):
        return "<top-level>"
    return "<other>"


def _status(vi_name: str) -> str:
    if vi_name in IMPLEMENTED:
        return "implemented"
    if vi_name in PARTIAL:
        return "partial"
    return "stub"


def _entries() -> list[PortEntry]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries: list[PortEntry] = []
    for item in manifest["documented_vis"]:
        vi_name = item["name"]
        entries.append(
            PortEntry(
                vi_name=vi_name,
                python_name=_python_name(vi_name),
                module=_module_name(vi_name),
                status=_status(vi_name),
                source_path=item.get("source_path"),
                images=item["images"],
            )
        )
    return entries


def _write_ports(entries: list[PortEntry]) -> None:
    lines = [
        '"""Generated registry for LabVIEW VI ports.',
        "",
        "Do not edit by hand; run tools/generate_port_registry.py.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "from typing import Callable",
        "",
        "",
        "@dataclass(frozen=True)",
        "class LabViewPort:",
        "    vi_name: str",
        "    python_name: str",
        "    module: str",
        "    status: str",
        "    source_path: str | None",
        "    images: tuple[str, ...]",
        "",
        "",
        "def not_implemented(*_args: object, **_kwargs: object) -> None:",
        '    raise NotImplementedError("This LabVIEW VI has not been semantically ported yet.")',
        "",
        "",
        "PORTS: dict[str, LabViewPort] = {",
    ]
    for entry in entries:
        lines.extend(
            [
                f"    {entry.vi_name!r}: LabViewPort(",
                f"        vi_name={entry.vi_name!r},",
                f"        python_name={entry.python_name!r},",
                f"        module={entry.module!r},",
                f"        status={entry.status!r},",
                f"        source_path={entry.source_path!r},",
                f"        images={tuple(entry.images)!r},",
                "    ),",
            ]
        )
    lines.extend(
        [
            "}",
            "",
            "CALLABLES: dict[str, Callable[..., object]] = {",
            "    name: not_implemented for name, port in PORTS.items() if port.status == 'stub'",
            "}",
            "",
        ]
    )
    PORTS_PATH.write_text("\n".join(lines), encoding="utf-8")


def _write_status(entries: list[PortEntry]) -> None:
    payload = {
        "total": len(entries),
        "implemented": sum(1 for entry in entries if entry.status == "implemented"),
        "partial": sum(1 for entry in entries if entry.status == "partial"),
        "stub": sum(1 for entry in entries if entry.status == "stub"),
        "entries": [entry.__dict__ for entry in entries],
    }
    STATUS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_tbd(entries: list[PortEntry]) -> None:
    by_module: dict[str, list[PortEntry]] = {}
    for entry in entries:
        by_module.setdefault(entry.module, []).append(entry)

    lines = [
        "# Porting TBD",
        "",
        "This file is generated from `labview_manifest.json` and records the current",
        "semantic porting status for every documented VI in `main_html/main`.",
        "Runtime and hardware validation items are maintained here as post-port tasks.",
        "",
        "## Summary",
        "",
        f"- Documented VI sections: {len(entries)}",
        f"- Implemented in Python: {sum(1 for e in entries if e.status == 'implemented')}",
        f"- Partially represented: {sum(1 for e in entries if e.status == 'partial')}",
        f"- Stub only: {sum(1 for e in entries if e.status == 'stub')}",
        "",
        "## Remaining Work By Module",
        "",
    ]

    for module in sorted(by_module):
        pending = [entry for entry in by_module[module] if entry.status != "implemented"]
        if not pending:
            continue
        lines.extend([f"### {module}", ""])
        for entry in pending:
            image_list = ", ".join(entry.images[:3])
            suffix = "..." if len(entry.images) > 3 else ""
            lines.append(f"- `{entry.status}` `{entry.vi_name}`: inspect `{image_list}{suffix}`")
        lines.append("")

    lines.extend(
        [
            "## Runtime / Hardware Validation",
            "",
            "The VI registry is semantically complete, but these items still need real-device",
            "validation or operator-facing polish before calling the Python app finished.",
            "",
        ]
    )
    for title, detail in RUNTIME_TBD:
        lines.append(f"- **{title}**: {detail}")
    lines.append("")

    TBD_PATH.parent.mkdir(parents=True, exist_ok=True)
    TBD_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    entries = _entries()
    _write_ports(entries)
    _write_status(entries)
    _write_tbd(entries)
    print(
        f"Generated {PORTS_PATH}, {STATUS_PATH}, and {TBD_PATH} "
        f"for {len(entries)} documented VIs."
    )


if __name__ == "__main__":
    main()
