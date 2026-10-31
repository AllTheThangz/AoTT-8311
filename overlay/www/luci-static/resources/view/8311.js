"use strict";
let configReview = null;
let configGeneration = 0;
let configWriteStarted = false;
let hookRevision = null;
let hookGeneration = 0;
let hookOpen = false;
let hookSaving = false;
let hookNeedsReload = false;
let hookBaseline = null;
let ponRequest = 0;
let currentJob = null;
let jobTimer = null;
let firmwareBankState = null;
let firmwareBusy = false;
let firmwareStatusTimer = null;
let firmwareRefreshInFlight = null;

/* Derive enabled firmware actions from the CURRENT bank state, never page-load HTML. */
function refreshArtifactControls() {
    if (!document.getElementById('upload-table')) return;
    const selection = document.querySelector('input[name="upload-selection"]:checked');
    const active = firmwareBusy || !!(currentJob && ['queued','running','cancel_requested'].includes(currentJob.state));
    $('#upload-empty').toggle($('#upload-table tbody tr').length === 0);
    $('.firmware-artifact').prop('disabled', !selection || active);
    $('#firmware-upload-btn').prop('disabled', active);
}
function refreshFirmwareControls() {
    if (!document.getElementById('bank-active')) return;
    const s = firmwareBankState || {};
    const safe = ['A','B'].includes(s.active) && ['A','B'].includes(s.committed) && s.boot_contract === true;
    const pending = ['A','B'].includes(s.pending);
    const trial = s.running_trial === true;
    const busy = firmwareBusy || !!(currentJob && ['queued','running','cancel_requested'].includes(currentJob.state));
    $('.firmware-bank').each(function() {
        let enabled = safe && !busy;
        const action = this.dataset.action, bank = this.dataset.bank;
        if (action === 'trial') {
            const item = s.banks && s.banks[bank];
            enabled = enabled && !pending && !trial && s.active !== bank && item && item.valid === true && item.receipt === 'complete';
        } else if (action === 'cancel_trial') {
            enabled = enabled && pending;
        } else if (action === 'commit') {
            enabled = enabled && !pending && trial;
        } else if (action === 'return_saved') {
            enabled = enabled && (s.active !== s.committed || pending);
        } else if (action === 'verify_bank') {
            enabled = enabled && s.banks && s.banks[bank] && s.banks[bank].receipt === 'complete';
        }
        this.disabled = !enabled;
    });
    refreshArtifactControls();
}
function refreshFirmwareState() {
    if (!document.getElementById('bank-active')) return Promise.resolve();
    if (firmwareRefreshInFlight) return firmwareRefreshInFlight;

    const message = $('#firmware-message');
    if (!firmwareBankState) message.removeClass('aott-error aott-success')
        .text('Verifying the live firmware banks…');

    firmwareRefreshInFlight = (async () => {
        for (let attempt = 1; attempt <= 3; attempt++) {
            try {
                const state = await request8311('bank_status');
                if (!state || state.schema !== 1 || !['A','B'].includes(state.active)
                    || !['A','B'].includes(state.committed) || state.boot_contract !== true) {
                    throw {error:'The device returned incomplete bank information.',_httpStatus:503};
                }
                updateBankState(state);
                const current = message.text();
                if (/^(Unable to read reliable bank state|The firmware bank is busy|The firmware-bank response|Verifying the live firmware|Cannot refresh bank state)/.test(current)) {
                    message.removeClass('aott-error').addClass('aott-success').text(
                        'Bank state verified: ' + state.active + ' running, ' +
                        state.committed + ' committed. No boot change was made.');
                }
                return state;
            } catch (error) {
                if (attempt < 3 && (error._httpStatus === 503 || !error._httpStatus)) {
                    await new Promise(resolve => setTimeout(resolve, attempt * 650));
                    continue;
                }
                firmwareBankState = null;
                refreshFirmwareControls();
                message.removeClass('aott-success').addClass('aott-error')
                    .text('Cannot verify bank state: ' + errorMessage(error) +
                        ' Firmware operations are locked until a successful refresh.');
                return null;
            }
        }
    })();
    return firmwareRefreshInFlight.finally(() => { firmwareRefreshInFlight = null; });
}


function switchTab(tab) {
    const tabs = Array.from(document.querySelectorAll('#aott-config-tabs [data-8311-tab]'));
    if (!tabs.some(item => item.getAttribute('data-8311-tab') === tab)) return false;
    tabs.forEach(link => {
        const selected = link.getAttribute('data-8311-tab') === tab;
        link.setAttribute('aria-selected', String(selected));
        link.tabIndex = selected ? 0 : -1;
        const parent = link.closest('li[data-tab]');
        if (parent) {
            parent.classList.toggle('cbi-tab', selected);
            parent.classList.toggle('cbi-tab-disabled', !selected);
        }
    });
    document.querySelectorAll('.aott-config-panel[data-tab]').forEach(panel => {
        const selected = panel.dataset.tab === tab;
        panel.hidden = !selected;
        if (selected) panel.setAttribute('data-tab-active', 'true');
        else panel.removeAttribute('data-tab-active');
    });
    return true;
}
function toggleSecret(id, button) {
	const input = document.getElementById(id);
	input.type = input.type === 'password' ? 'text' : 'password';
	button.textContent = input.type === 'password' ? 'Reveal' : 'Hide';
}
function token8311() {
	return $('#8311-token').val() || $('#8311-config input[name="token"]').val();
}
function errorMessage(error) {
	if (error && error.errors) return Object.keys(error.errors).map(key => key + ': ' + error.errors[key]).join('\n');
	return error && (error.error || error.message) || 'The request failed. Check the connection and reload before retrying.';
}
async function request8311(url, options) {
	const response = await fetch(url, Object.assign({credentials: 'same-origin', cache: 'no-store'}, options || {}));
	let record;
	try { record = await response.json(); }
	catch (_) { throw {error: 'The device returned an incomplete response or your login has expired.', _httpStatus: response.status}; }
	if (!response.ok || record.success === false) { record._httpStatus = response.status; throw record; }
	return record;
}
function post8311(url, values) {
	const body = new URLSearchParams(Object.assign({token: token8311()}, values));
	return request8311(url, {method: 'POST', body: body});
}
function showFieldErrors(record) {
	$('.cbi-value-error').hide().text('');
	$('#8311-config [name]').removeAttr('aria-invalid');
	Object.keys(record.errors || {}).forEach(name => {
		$('.cbi-value-error').filter(function() { return $(this).attr('data-error-for') === name; }).text(record.errors[name]).show();
		$('#8311-config [name]').filter(function() { return this.name === name; }).attr('aria-invalid', 'true');
	});
    $('#config-message').removeClass('aott-success aott-warning').addClass('aott-error').text(errorMessage(record));
}
function renderDiff(rows, parent, labels) {
	parent.textContent = '';
	if (!rows.length) { parent.textContent = 'No setting changes.'; return; }
	const table = document.createElement('table'); table.className = 'table';
	const header = document.createElement('tr');
	labels.forEach(label => { const cell = document.createElement('th'); cell.textContent = label; header.appendChild(cell); });
	table.appendChild(header);
	rows.forEach(row => {
		const line = document.createElement('tr');
		[row.name, row.before, row.after, row.applies].forEach(value => { const cell = document.createElement('td'); cell.textContent = value; line.appendChild(cell); });
		table.appendChild(line);
	});
	parent.appendChild(table);
}
function configPayload(form) {
	const data = new URLSearchParams(new FormData(form)); data.set('mode', 'preview');
	return data.toString();
}
function invalidateConfigReview(message) {
	++configGeneration; configReview = null;
	$('#config-review').hide(); $('#config-confirm').prop('disabled', true);
	if (!configWriteStarted) $('#save-btn').prop('disabled', false);
	if (message) $('#config-message').text(message);
}
function currentConfigPreview(sequence, body, form) {
	if (sequence !== configGeneration || configWriteStarted) return false;
	if (configPayload(form) !== body) {
		invalidateConfigReview('Values changed while validation was in progress. Review the current form again.');
		return false;
	}
	return true;
}
function rejectedBeforeWrite(error) {
	return error && error.success === false && !error.durability_unknown &&
		[400,409,413,422].includes(error._httpStatus);
}
function writeFailureMessage(error, subject) {
	let message = errorMessage(error) + '\n';
	if (rejectedBeforeWrite(error)) message += 'The device rejected this request before changing ' + subject + '.';
	else message += 'The save outcome is not confirmed. ' + subject + ' may have changed; do not repeat this save blindly.';
	if (error.verified && error.verified.length) message += ' Verified writes: ' + error.verified.join(', ') + '.';
	return message;
}
function saveConfig(form) {
	if (configWriteStarted) return false;
	const sequence = ++configGeneration;
	const button = $('#save-btn'); button.prop('disabled', true);
	$('#config-message').text('Checking the complete configuration and current revision…');
	configReview = null; $('#config-review').hide();
	const body = configPayload(form), data = new URLSearchParams(body);
	request8311(form.action, {method: 'POST', body: data}).then(record => {
		if (!currentConfigPreview(sequence, body, form)) return;
		if (record.success !== true || !Array.isArray(record.diff) || record.revision !== data.get('revision')) throw {error: 'Validation returned an incomplete response. Reload before reviewing again.'};
		$('.cbi-value-error').hide().text('');
		$(form).find('[name]').removeAttr('aria-invalid');
		renderDiff(record.diff, document.getElementById('config-diff'), ['Setting', 'Saved value', 'Proposed value', 'When used']);
        $('#config-message').removeClass('aott-error aott-warning').addClass('aott-success').text('Validation passed. Review the changes below before saving.');
		data.set('mode', 'apply'); configReview = {preview:body, apply:data.toString(), sequence:sequence, changed:record.diff.length > 0};
		$('#config-confirm').prop('disabled', !configReview.changed);
		$('#config-review').show();
	}).catch(error => { if (currentConfigPreview(sequence, body, form)) showFieldErrors(error); })
		.finally(() => { if (sequence === configGeneration && !configWriteStarted) button.prop('disabled', false); });
	return false;
}
function openHookEditor() {
	if (hookSaving) return;
	hookOpen = true; $('#hook-script-modal').show();
	if (hookNeedsReload) return;
	const sequence = ++hookGeneration;
	hookRevision = null; hookBaseline = null;
	$('#hook-script-textarea').val('').prop('readOnly', true);
	$('#hook-script-save-btn').prop('disabled', true);
	$('#hook-script-message').text('Loading the saved hook…');
	request8311('get_hook_script').then(record => {
		if (sequence !== hookGeneration || !hookOpen) return;
		if (typeof record.content !== 'string' || typeof record.revision !== 'string' || !/^[a-f0-9]{64}$/.test(record.revision)) throw {error: 'The saved hook response was incomplete. Close and reopen the editor.'};
		hookRevision = record.revision; hookBaseline = record.content;
		$('#hook-script-textarea').val(record.content).prop('readOnly', false);
		$('#hook-script-message').text(record.previous_available ? 'Saved hook loaded. One previous copy is retained on the device.' : 'Saved hook loaded.');
	}).catch(error => {
		if (sequence === hookGeneration && hookOpen) $('#hook-script-message').text(errorMessage(error));
	});
}
function hookDraftChanged() {
	if (!hookRevision || hookSaving || hookNeedsReload) return;
	const changed = $('#hook-script-textarea').val() !== hookBaseline;
	$('#hook-script-save-btn').prop('disabled', !changed);
	$('#hook-script-message').text(changed ? 'Unsaved hook changes. This draft has not been syntax-checked.' : 'The editor matches the saved hook.');
}
function saveHookEditor() {
	if (!hookOpen || !hookRevision || hookSaving || hookNeedsReload) return;
	const content = $('#hook-script-textarea').val();
	if (content === hookBaseline) return;
	const sequence = hookGeneration, revision = hookRevision;
	hookSaving = true;
	$('#hook-script-textarea').prop('readOnly', true);
	$('#hook-script-save-btn,#hook-script-cancel-btn,#edit-hook-script-btn').prop('disabled', true);
	$('#hook-script-message').text('Saving the submitted hook and checking readback…');
	post8311('save_hook_script', {content:content, revision:revision}).then(record => {
		if (sequence !== hookGeneration || !hookOpen) return;
		if (record.success !== true || typeof record.revision !== 'string' || !/^[a-f0-9]{64}$/.test(record.revision)) throw {error:'The hook save response was incomplete.'};
		hookRevision = record.revision; hookBaseline = content;
		const changed = $('#hook-script-textarea').val() !== content;
		$('#hook-script-message').text(changed ? 'The submitted hook was saved and read back. The text now shown has newer unsaved changes and has not been syntax-checked.' : (content === '' ? 'Hook deleted and absence read back. The script was not executed.' : 'Submitted hook saved and read back. Shell syntax check passed; the script was not executed.'));
	}).catch(error => {
		if (sequence !== hookGeneration || !hookOpen) return;
		const correctable = rejectedBeforeWrite(error) && error._httpStatus !== 409;
		hookNeedsReload = !correctable;
		if (hookNeedsReload) hookRevision = null;
		$('#hook-script-message').text(writeFailureMessage(error, 'the hook') + (correctable ? ' Correct the draft before saving again.' : ' Copy any draft you need, then reload this page and read the saved hook before another save.'));
	}).finally(() => {
		hookSaving = false;
		$('#hook-script-cancel-btn,#edit-hook-script-btn').prop('disabled', false);
		if (sequence !== hookGeneration || !hookOpen) return;
		$('#hook-script-textarea').prop('readOnly', hookNeedsReload);
		$('#hook-script-save-btn').prop('disabled', !hookRevision || hookNeedsReload || $('#hook-script-textarea').val() === hookBaseline);
	});
}
function vlanTables() {
    const report = $('#vlan-report');
    if (!report.length) return;
    report.text('Loading VLAN tables…').attr('aria-busy','true');
    $('#vlan-report-status').text('Reading the current OLT and local mappings…');
    $.ajax({url:'vlans/extvlans', dataType:'text', timeout:20000}).done(data => {
        report.text(data || 'No mapping records were returned.');
        $('#vlan-report-status').text('Read-only VLAN inspection completed.');
    }).fail(xhr => {
        report.text('VLAN data is not available.');
        $('#vlan-report-status').text('VLAN inspection failed (HTTP ' + (xhr.status || 'unavailable') + '). Check PON/OMCI health and retry.');
    }).always(() => report.attr('aria-busy','false'));
}
function switchTabPonStatus(tab) {
    const picker = document.getElementById('pon-status-picker');
    if (!picker || !Array.from(picker.options).some(option => option.value === tab)) return;
    picker.value = tab;
    $('.aott-pon-quick').each(function() {
        this.setAttribute('aria-pressed', String(this.getAttribute('data-pon-status-tab') === tab));
    });
    const selected = picker.options[picker.selectedIndex];
    const label = selected ? selected.textContent : tab;
    $('#pon-report-title').text(label);
    $('#pon-report-status').text('Reading ' + label + ' from the device…');
    const report = $('#pon-report');
    report.text('Loading…').attr('aria-busy','true');
    const sequence = ++ponRequest;
    $.ajax({url:'pontop/' + encodeURIComponent(tab),dataType:'text',timeout:20000}).done(data => {
        if (sequence !== ponRequest) return;
        report.text(data || 'No information was returned.');
        $('#pon-report-status').text('Report updated. Read-only, no changes were made.');
    }).fail(xhr => {
        if (sequence !== ponRequest) return;
        report.text('The requested PON report is unavailable.');
        $('#pon-report-status').text('Status read failed (HTTP ' + (xhr.status || 'unavailable') + '). Select another report or retry.');
    }).always(() => { if (sequence === ponRequest) report.attr('aria-busy','false'); });
}
let meRequest = 0;
function filterPonMe() {
    const text = String($('#me-filter').val() || '').trim().toLocaleLowerCase();
    let matches = 0, total = 0;
    $('#me-list .aott-me-line').each(function() {
        const isME = this.hasAttribute('data-me-entry');
        const visible = !text || this.textContent.toLocaleLowerCase().includes(text);
        this.hidden = !visible;
        if (isME) {total++; if (visible) matches++;}
    });
    $('#me-filter-count').text(matches + ' of ' + total + ' Managed Entities shown. Select an entry to inspect its attributes.');
}
function showPonMe(meId, instanceId) {
    const sequence = ++meRequest;
    const validId = value => /^\d{1,5}$/.test(String(value)) && Number(value) <= 65535;
    if (!validId(meId) || !validId(instanceId)) {
        $('#me-status').text('Invalid Managed Entity identifier. No request was sent.');
        $('#me_dump').hide().attr('aria-busy','false');
        return;
    }
    const base = String($('#me-list').attr('data-dump-base') || '').replace(/\/+$/, '');
    if (!base || !base.startsWith('/') || base.includes('?') || base.includes('#')) {
        $('#me-status').text('Managed Entity read endpoint is unavailable.');
        $('#me_dump').hide().attr('aria-busy','false');
        return;
    }
    $('#me_label').text('Class ' + meId + ' · Instance ' + instanceId);
    $('#me-status').text('Reading selected Managed Entity…');
    $('#me_dump').text('Loading…').show().attr('aria-busy','true');
    $.ajax({url:base + '/' + encodeURIComponent(meId) + '/' + encodeURIComponent(instanceId),
            dataType:'text',cache:false,timeout:20000}).done(data => {
        if (sequence !== meRequest) return;
        $('#me_dump').text(data || 'No entity attributes were returned.').show();
        $('#me-status').text('Live OMCI attributes retrieved; no changes made.');
    }).fail(xhr => {
        if (sequence !== meRequest) return;
        $('#me_dump').text('Managed Entity read failed (HTTP ' + (xhr.status || 'unavailable') + ').').show();
        $('#me-status').text('The entity could not be read; no changes were made.');
    }).always(() => { if (sequence === meRequest) $('#me_dump').attr('aria-busy','false'); });
}
function updateBankState(state) {
    if (!state || state.schema !== 1) {
        firmwareBankState = null;
        refreshFirmwareControls();
        return;
    }
    firmwareBankState = state;
	$('#bank-active').text(state.active || 'unknown'); $('#bank-committed').text(state.committed || 'unknown');
	$('#bank-pending').text(state.pending || 'none'); $('#bank-contract').text(state.boot_contract === true ? 'verified' : 'unknown');
	$('#bank-receipts').text(JSON.stringify(state.banks || {}, null, 2));
	$('#bank-explanation').text(state.pending ? 'The next reboot boots the pending bank once. Later resets return to the saved bank unless the trial is kept.' : state.running_trial ? 'This is a trial boot. A reset returns to the saved bank unless the running firmware is kept.' : 'No one-time trial is scheduled.');
	['A','B'].forEach(name => {
		const bank = state.banks && state.banks[name] || {};
		$('#receipt-' + name).text(bank.receipt || 'unknown');
		$('#valid-' + name).text(bank.valid === true ? 'valid' : bank.valid === false ? 'invalid' : 'unknown');
	});
    refreshFirmwareControls();
}
function jobKey() { return '8311-job-' + ($('#job-panel').attr('data-kind') || 'unknown'); }
function showJob(record) {
	currentJob = record;
	const active = ['queued','running','cancel_requested'].includes(record.state);
	let status = record.kind + ' / ' + record.id + ': ' + record.state;
	if (record.exitcode !== undefined && record.exitcode !== null) status += ' (exit ' + record.exitcode + ')';
	if (record.partial) status += ': PARTIAL archive; collection did not complete successfully';
	if (record.created) status += '\nCreated: ' + new Date(record.created * 1000).toLocaleString();
	$('#job-state').text(status);
	$('#job-output').text((record.error ? record.error + '\n' : '') + (record.output || ''));
	$('#job-cancel').toggle(active && record.kind === 'support' && record.state !== 'cancel_requested');
	$('#support-download').toggle(!!record.download_ready).attr('href', 'support/support.tar.gz?job_id=' + encodeURIComponent(record.id));
    if ($('#bank-active').length) {
        firmwareBusy = active;
        refreshFirmwareControls();
        if (!active) refreshFirmwareState();
    }
    $('#support-start').prop('disabled', active);
	return active;
}
function monitorJob(record) {
	if (jobTimer) clearTimeout(jobTimer);
	sessionStorage.setItem(jobKey(), record.id);
	const active = showJob(record);
	if (active) jobTimer = setTimeout(() => pollJob(record.id), 2000);
}
function pollJob(id) {
	request8311('job_status?id=' + encodeURIComponent(id)).then(monitorJob).catch(error => {
		if (sessionStorage.getItem(jobKey() + '-reboot') === '1') { recoverBankAfterReboot(); return; }
		$('#job-state').text('Status unavailable: ' + errorMessage(error) + ' The job may still be running.');
		if (error._httpStatus === 403 || error._httpStatus === 404) {
            sessionStorage.removeItem(jobKey());
            currentJob = null; firmwareBusy = false;
            refreshFirmwareState();
            return;
        }
		jobTimer = setTimeout(() => pollJob(id), 10000);
	});
}
function recoverBankAfterReboot() {
	$('#job-state').text('The reboot connection was interrupted. Waiting for live bank state; the action will not be repeated.');
	request8311('bank_status').then(state => {
		updateBankState(state); sessionStorage.removeItem(jobKey()); sessionStorage.removeItem(jobKey() + '-reboot');
		$('#job-state').text('Live bank state is available above. The prior temporary job record is unavailable; verify the running and saved banks and service health.');
        firmwareBusy = false;
        currentJob = null;
        refreshFirmwareControls();
	}).catch(() => { jobTimer = setTimeout(recoverBankAfterReboot, 5000); });
}
function appendUpload(upload) {
	const row = document.createElement('tr'); row.className = 'tr';
	const select = document.createElement('td'), radio = document.createElement('input');
	radio.type = 'radio'; radio.name = 'upload-selection'; radio.value = upload.upload_id; radio.dataset.sha256 = upload.sha256; radio.checked = true;
	select.appendChild(radio); row.appendChild(select);
	[upload.filename, upload.size, upload.sha256].forEach(value => { const cell = document.createElement('td'); cell.style.overflowWrap = 'anywhere'; cell.textContent = value; row.appendChild(cell); });
	document.querySelector('#upload-table tbody').appendChild(row);
    document.querySelectorAll('input[name="upload-selection"]').forEach(input => {
        input.checked = input === radio;
    });
    refreshArtifactControls();
}
function uploadFirmware(form) {
	const file = document.getElementById('firmware-file').files[0];
	if (!file || file.size === 0 || file.size > 24 * 1024 * 1024) { $('#firmware-message').text('Choose one nonempty archive up to 24 MiB.'); return false; }
	const body = new FormData(); body.append('firmware_file', file);
	$('#firmware-upload-btn').prop('disabled', true); $('#upload-progress').text('Uploading and calculating SHA-256…');
	request8311('firmware_upload', {method: 'POST', headers: {'X-CSRF-Token': token8311()}, body: body}).then(record => {
		appendUpload(record.upload); $('#upload-progress').text('Upload complete. Review its filename, byte count and digest before installing.'); form.reset();
	}).catch(error => $('#upload-progress').text(errorMessage(error))).finally(() => $('#firmware-upload-btn').prop('disabled', false));
	return false;
}
function startSupport(form) {
	const full = $('#support-mode').val();
	if (full === '1' && !window.confirm('Generate a full private archive containing identity, configuration and logs?')) return false;
	$('#support-start').prop('disabled', true); $('#support-message').text('Starting diagnostics…');
	post8311('support', {action: 'generate', full: full}).then(record => { $('#support-message').text(''); monitorJob(record); }).catch(error => { $('#support-message').text(errorMessage(error)); $('#support-start').prop('disabled', false); });
	return false;
}
$(document).ready(function() {
    $(document).on('click', 'a[data-8311-tab]', function(event) {
        event.preventDefault();
        const tab = $(this).attr('data-8311-tab');
        if (switchTab(tab)) history.replaceState(null,'','#8311-tab-' + tab);
    });
    $('#aott-config-tabs').on('keydown','[role="tab"]',function(event) {
        const tabs = Array.from(document.querySelectorAll('#aott-config-tabs [role="tab"]'));
        const position = tabs.indexOf(this);
        let next = position;
        if (event.key === 'ArrowRight') next = (position + 1) % tabs.length;
        else if (event.key === 'ArrowLeft') next = (position + tabs.length - 1) % tabs.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = tabs.length-1;
        else return;
        event.preventDefault();
        const tab=tabs[next].getAttribute('data-8311-tab');
        if (switchTab(tab)) {
            history.replaceState(null,'','#8311-tab-' + tab);
            tabs[next].focus();
        }
    });
    if (document.getElementById('aott-config-tabs')) {
        const match = location.hash.match(/^#8311-tab-(pon|isp|manage|device|sfp)$/);
        if (match) switchTab(match[1]);
        window.addEventListener('hashchange',() => {
            const selected=location.hash.match(/^#8311-tab-(pon|isp|manage|device|sfp)$/);
            if (selected) switchTab(selected[1]);
        });
    }
    $(document).on('click', 'button[data-pon-status-tab]', function(event) {
        event.preventDefault();
        switchTabPonStatus($(this).attr('data-pon-status-tab'));
    });
    $('#pon-status-picker').on('change',function() { switchTabPonStatus(this.value); });
    $('#pon-status-refresh').on('click',function() {
        const picker=document.getElementById('pon-status-picker');
        if (picker) switchTabPonStatus(picker.value);
    });
    $('#vlan-refresh').on('click',vlanTables);
    $('#me-filter').on('input',filterPonMe);
    $('#me-clear').on('click',function() {
        $('#me-filter').val('').trigger('input').focus();
    });
    if ($('#me-list').length) filterPonMe();
	$(document).on('click', 'a[data-me-id][data-instance-id]', function(event) {
		event.preventDefault();
		showPonMe($(this).attr('data-me-id'), $(this).attr('data-instance-id'));
	});
	$('#8311-config').on('input change', function() {
		if (!configWriteStarted) invalidateConfigReview('Values changed. Review the complete form before saving.');
	});
	$('#config-confirm').on('click', function() {
		if (!configReview || !configReview.changed || configWriteStarted) return;
		const form = document.getElementById('8311-config');
		if (configReview.sequence !== configGeneration || configReview.preview !== configPayload(form)) {
			invalidateConfigReview('The form no longer matches the reviewed changes. Review it again before saving.'); return;
		}
		const body = configReview.apply;
		const submitted = Array.from(form.elements).filter(input => input.name).map(input => ({input:input,value:input.value}));
		configWriteStarted = true; configReview = null; ++configGeneration;
		$(form).find('input:not([type="hidden"]),select,textarea,button').prop('disabled', true);
		$(form).attr('aria-busy', 'true'); $('#config-confirm').prop('disabled', true);
		$('#config-message').text('Saving the reviewed settings. Keep this page open until the outcome is shown.');
		request8311(form.action, {method:'POST', body:new URLSearchParams(body)}).then(record => {
			if (record.success !== true || !Array.isArray(record.verified)) throw {error:'The settings save response was incomplete.'};
			const changed = submitted.some(item => item.input.value !== item.value);
			$('#config-message').text('Reviewed settings saved and read back. ' + (record.warning || '') +
				(changed ? ' Values changed in this page after submission are not saved.' : '') + ' Reload this page to inspect the saved values and updated startup comparison.');
		}).catch(error => {
			showFieldErrors(error);
			$('#config-message').text(writeFailureMessage(error, 'the settings') + ' Reload this page and inspect the durable values before another save.');
		}).finally(() => $(form).attr('aria-busy', 'false'));
		$('#config-review').hide();
	});
	const fix = document.getElementById('widget.cbid.system.poncfg.fix_vlans');
	if (fix) {
		const toggle = () => $('.vlan-field').toggle(fix.value === '1'); $(fix).on('change', toggle); toggle();
		$('#edit-hook-script-btn').on('click', openHookEditor);
		$('#hook-script-textarea').on('input change', hookDraftChanged);
		$('#hook-script-save-btn').on('click', saveHookEditor);
		$('#hook-script-cancel-btn').on('click', () => {
			if (hookSaving) return;
			++hookGeneration; hookOpen = false; hookRevision = null; $('#hook-script-modal').hide();
		});
	}
	$('.firmware-bank').on('click', function() {
		const prompt = $(this).attr('data-confirm'); if (prompt && !window.confirm(prompt)) return;
		const action = $(this).attr('data-action'), values = {action: action};
		if ($(this).attr('data-bank')) values.bank = $(this).attr('data-bank');
		const reboot = action === 'reboot' || action === 'return_saved';
		if (reboot) sessionStorage.setItem(jobKey() + '-reboot', '1'); else sessionStorage.removeItem(jobKey() + '-reboot');
        firmwareBusy = true;
        refreshFirmwareControls();
        $('#firmware-message').text('Submitting checked bank job…');
        post8311('firmware', values).then(record => {
            $('#firmware-message').text('Bank job accepted. ' + (reboot ? 'Expect a disconnect if the checked reboot proceeds.' : ''));
            monitorJob(record);
        }).catch(error => {
            $('#firmware-message').text(errorMessage(error) + ' Refresh live bank status before trying another operation.');
            if (reboot && !error._httpStatus) recoverBankAfterReboot();
            else if (reboot) sessionStorage.removeItem(jobKey() + '-reboot');
        }).finally(() => {
            if (!currentJob || !['queued','running','cancel_requested'].includes(currentJob.state)) {
                firmwareBusy = false; refreshFirmwareState();
            }
            refreshFirmwareControls();
        });
	});
	$('.firmware-artifact').on('click', function() {
		const selection = document.querySelector('input[name="upload-selection"]:checked');
		if (!selection) { $('#firmware-message').text('Select an upload first.'); return; }
		const prompt = $(this).attr('data-confirm'); if (prompt && !window.confirm(prompt)) return;
		const action = $(this).attr('data-action');
        firmwareBusy = true;
        refreshFirmwareControls();
        post8311('firmware', {action: action,upload_id: selection.value,sha256: selection.dataset.sha256}).then(record => {
            if (action === 'discard_upload') {
                selection.closest('tr').remove();
                const first = document.querySelector('input[name="upload-selection"]');
                if (first) first.checked = true;
                $('#firmware-message').text('Upload discarded. The boot selection is unchanged.');
            } else {
                $('#firmware-message').text('Background job accepted. The log below will update as the device responds.');
                monitorJob(record);
            }
        }).catch(error => $('#firmware-message').text(errorMessage(error))).finally(() => {
            if (!currentJob || !['queued','running','cancel_requested'].includes(currentJob.state)) firmwareBusy = false;
            refreshFirmwareControls();
        });
	});
	$('#job-cancel').on('click', () => { if (currentJob) post8311('job_cancel', {id: currentJob.id}).then(monitorJob).catch(error => $('#support-message').text(errorMessage(error))); });
    $('#bank-refresh-btn').on('click', function() {
        $(this).prop('disabled', true);
        refreshFirmwareState().finally(() => $(this).prop('disabled', false));
    });
    $(document).on('change', 'input[name="upload-selection"]', refreshArtifactControls);
    if ($('#bank-active').length) {
        refreshFirmwareControls();
        refreshFirmwareState();
        firmwareStatusTimer = setInterval(() => {
            if (!firmwareBusy && !(currentJob && ['queued','running','cancel_requested'].includes(currentJob.state))) {
                refreshFirmwareState();
            }
        }, 30000);
        window.addEventListener('pagehide', () => { if (firmwareStatusTimer) clearInterval(firmwareStatusTimer); });
    }
    if ($('#job-panel').length) { const id = sessionStorage.getItem(jobKey()); if (id) pollJob(id); }
});
