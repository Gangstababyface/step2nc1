"""Stable customer-facing failure codes and next actions."""

def diagnose(error):
    message=str(error);text=message.lower()
    rules=[
        ('cancel', 'CANCELLED', 'Conversion cancelled.', 'Run the conversion again when ready.'),
        ('exceeded', 'TIMEOUT', 'The model exceeded the processing time limit.', 'Try one part at a time. Send the STEP file and support report if it still times out.'),
        ('exited unexpectedly', 'CAD_PROCESS_FAILED', 'The geometry engine stopped unexpectedly.', 'The application is still usable. Keep this file for investigation and include the support report.'),
        ('ascii', 'HEADER_TEXT', 'An NC1 header contains unsupported characters.', 'Open the draft and use plain ASCII text in the named header field. The original STEP filename can stay unchanged.'),
        ('expected one solid', 'ASSEMBLY', 'This file does not contain exactly one solid part.', 'Export each solid as a separate STEP file, then convert those files.'),
        ('invalid or empty', 'INVALID_SOLID', 'The STEP solid is invalid or empty.', 'Repair the solid in the source CAD application and export it again.'),
        ('round pipe:', 'ROUND_CUT_UNSUPPORTED', 'This round-pipe cut is outside the supported scope.', 'Square and single-plane mitered pipe ends are supported. Keep saddles, bores and stepped ends in the source CAM workflow.'),
        ('constant w', 'SECTION_NOT_RECOGNIZED', 'The stock section could not be identified.', 'Try the source length-axis override. Check that the model is a single straight supported section.'),
        ('no straight', 'SECTION_NOT_RECOGNIZED', 'No straight stock axis was found.', 'Check for a curved member or unsupported stock section.'),
        ('thickness', 'THROUGH_THICKNESS_GEOMETRY', 'A cut changes through the material thickness.', 'Review the model for blind pockets, angled holes or unsupported bevels. Do not substitute a face outline for the full cut.'),
        ('already exists', 'OUTPUT_EXISTS', 'An output file already exists.', 'Choose another output folder or explicitly allow replacement.'),
        ('file exists', 'OUTPUT_EXISTS', 'An output file already exists.', 'Choose another output folder or explicitly allow replacement.'),
        ('exists; use --force', 'OUTPUT_EXISTS', 'An output file already exists.', 'Choose another output folder or use --force to replace it.'),
    ]
    for match,code,summary,action in rules:
        if match in text:return dict(code=code,summary=summary,action=action,detail=message)
    return dict(code='REVIEW_REQUIRED',summary='This part needs review.',action='Read the detailed diagnostic. Include the source file and support report when requesting help.',detail=message)


def describe_result(row):
    if row.get('status')!='ok':row['diagnostic']=diagnose(row.get('error','Conversion failed.'))
    return row
