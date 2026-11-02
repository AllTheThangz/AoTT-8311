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
let firmwareBankStateVerifiedAt = 0;
const FIRMWARE_BANK_STATE_MAX_AGE_MS = 60000;

/* Derive enabled firmware actions from the CURRENT bank state, never page-load HTML. */
function refreshArtifactControls() {
    if (!document.getElementById('upload-table')) return;
    const selection = document.querySelector('input[name="upload-selection"]:checked');
    const active = firmwareBusy || !!(currentJob && ['queued','running','cancel_requested'].includes(currentJob.state));
    $('#upload-empty').toggle($('#upload-table tbody tr').length === 0);
    $('.firmware-artifact').each(function() {
        const action = this.dataset.action;
        this.disabled = !selection || active ||
            (action === 'install' &&
             (!firmwareBankStateFresh() ||
              !firmwareInstallImpact(firmwareBankState).ready));
    });
    $('#firmware-upload-btn').prop('disabled', active);
}
function verifiedBankSnapshot(state) {
    if (!state || typeof state.state_guard !== 'string' ||
        !/^[0-9a-f]{64}$/.test(state.state_guard) ||
        state.schema !== 1 || state.boot_contract !== true ||
        !['A','B'].includes(state.active) || !['A','B'].includes(state.committed) ||
        typeof state.running_trial !== 'boolean' ||
        !Object.prototype.hasOwnProperty.call(state, 'pending') ||
        !(state.pending === null || ['A','B'].includes(state.pending)) ||
        state.running_trial !== (state.active !== state.committed) ||
        (state.pending !== null &&
         (state.running_trial || state.pending === state.active ||
          state.active !== state.committed))) return false;
    const banks = state.banks;
    if (!banks || !['A','B'].every(bank => {
        const record = banks[bank];
        return !!record && typeof record.valid === 'boolean' &&
            typeof record.receipt === 'string';
    })) return false;
    // Every bank on the running, saved, or pending boot path must be complete.
    // The other bank may remain invalid while the operator investigates it.
    const required = [state.active, state.committed, state.pending].filter(Boolean);
    return required.every(bank =>
        banks[bank].valid === true && banks[bank].receipt === 'complete');
}
function firmwareRebootPlan(state) {
    if (!verifiedBankSnapshot(state)) return {
        next: 'Unknown, refresh required',
        recovery: 'Unverified',
        explanation: 'The current boot selection is not verified. Bank actions remain locked.'
    };
    if (state.pending !== null) return {
        next: 'Bank ' + state.pending + ' (one-time boot)',
        recovery: 'Bank ' + state.committed + ' (saved)',
        explanation: 'The next reboot tries bank ' + state.pending +
            ' once. Bank ' + state.committed +
            ' stays committed. A further reset returns to the saved bank unless the trial is committed.'
    };
    if (state.running_trial) return {
        next: 'Bank ' + state.committed + ' (saved)',
        recovery: 'Bank ' + state.committed + ' (saved)',
        explanation: 'Bank ' + state.active +
            ' is running as an uncommitted trial. A reboot returns to bank ' +
            state.committed + ' unless the trial is explicitly committed.'
    };
    return {
        next: 'Bank ' + state.committed + ' (committed)',
        recovery: 'Bank ' + state.committed + ' (committed)',
        explanation: 'Bank ' + state.committed +
            ' is running and committed. No one-time trial is pending.'
    };
}
function firmwareInstallImpact(state) {
    if (!verifiedBankSnapshot(state)) return {
        target: null, ready: false,
        explanation: 'The inactive bank has not been verified. Refresh live ' +
            'bank status before considering an installation.'
    };
    const target = state.active === 'A' ? 'B' : 'A';
    const candidate = state.banks[target];
    const protectedState = state.active === state.committed &&
        state.pending === null && state.running_trial === false;
    const description = candidate.valid === true && candidate.receipt === 'complete'
        ? 'currently contains a valid firmware image'
        : 'does not have a complete, valid image receipt';
    const explanation = 'A new firmware archive would OVERWRITE bank ' + target +
        ', which ' + description + '. The running and committed bank ' +
        state.active + ' would be preserved by the installer. ' +
        'Make and independently verify fresh, off-device full-bank backups ' +
        'of BOTH A and B before proceeding.';
    return {
        target: target, ready: protectedState,
        explanation: protectedState ? explanation :
            'Installation is locked while a trial or pending boot is ' +
            'active. Resolve the boot selection before installing. ' + explanation
    };
}
function firmwareBankGuardSignature(state) {
    if (!verifiedBankSnapshot(state)) return null;
    const parts = ['A','B'].map(bank => {
        const item = state.banks[bank];
        const components = item.components || {};
        return [bank, item.valid, item.receipt, ['kernel','bootcore','rootfs']
            .map(part => {
                const image = components[part] || {};
                return [image.bytes ?? null, image.sha256 ?? null];
            })];
    });
    return JSON.stringify([state.active, state.committed, state.pending,
        state.running_trial, state.boot_contract, state.state_guard, parts]);
}
function firmwareBankStateFresh() {
    const elapsed = Date.now() - firmwareBankStateVerifiedAt;
    return verifiedBankSnapshot(firmwareBankState) &&
        firmwareBankStateVerifiedAt > 0 &&
        elapsed >= 0 && elapsed < FIRMWARE_BANK_STATE_MAX_AGE_MS;
}
function firmwareBankActionAllowed(state, action, bank) {
    if (!verifiedBankSnapshot(state)) return false;
    if (action === 'trial') {
        const item = state.banks[bank];
        return !!item && bank !== state.active && state.pending === null &&
            state.running_trial === false && item.valid === true &&
            item.receipt === 'complete';
    }
    if (action === 'cancel_trial') return state.pending !== null;
    if (action === 'commit') return state.pending === null && state.running_trial === true;
    if (action === 'return_saved') return state.active !== state.committed ||
        state.pending !== null;
    if (action === 'verify_bank') return !!state.banks[bank] &&
        state.banks[bank].receipt === 'complete';
    if (action === 'reboot') return true;
    // Unknown buttons must never inherit enabled behavior.
    return false;
}
function refreshFirmwareControls() {
    if (!document.getElementById('bank-active')) return;
    const safe = firmwareBankStateFresh();
    const busy = firmwareBusy || !!(currentJob &&
        ['queued','running','cancel_requested'].includes(currentJob.state));
    const age = Date.now() - firmwareBankStateVerifiedAt;
    const label = !verifiedBankSnapshot(firmwareBankState)
        ? 'Live bank state unavailable. Refresh before changing firmware.'
        : !safe
            ? 'Bank state is stale. Refresh before changing firmware.'
            : 'Bank state checked in this browser ' +
              Math.floor(Math.max(0, age) / 1000) + ' seconds ago.';
    $('#bank-state-freshness').text(label);
    const impact = firmwareInstallImpact(firmwareBankState);
    $('#bank-install-impact').text(safe ? impact.explanation :
        'The inactive bank is not verified for installation. Refresh ' +
        'live bank status and independently back up BOTH firmware banks.');
    $('.firmware-bank').each(function() {
        this.disabled = !safe || busy || !firmwareBankActionAllowed(
            firmwareBankState, this.dataset.action, this.dataset.bank);
    });
    refreshArtifactControls();
}
async function submitCheckedFirmwareBankAction(button) {
    if (!button || button.disabled || firmwareBusy || !firmwareBankStateFresh()) {
        return;
    }
    const action = button.dataset.action, bank = button.dataset.bank;
    const observed = firmwareBankGuardSignature(firmwareBankState);
    if (!observed || !firmwareBankActionAllowed(firmwareBankState, action, bank)) {
        return;
    }
    const reboot = action === 'reboot' || action === 'return_saved';
    let submitted = false;
    let liveCheckSucceeded = false;
    firmwareBusy = true;
    refreshFirmwareControls();
    $('#firmware-message').text('Checking live bank state before submitting any operation.');
    try {
        // Obtain a fresh, authenticated response immediately before confirmation.
        // The backend must still independently enforce all boot/flash controls.
        const current = await request8311('bank_status');
        liveCheckSucceeded = true;
        if (!verifiedBankSnapshot(current)) {
            updateBankState(null);
            throw {error: 'The live bank state is invalid. No operation was sent.'};
        }
        const currentSignature = firmwareBankGuardSignature(current);
        updateBankState(current);
        if (currentSignature !== observed) {
            throw {error: 'Bank state changed since the page was reviewed. ' +
                'Inspect the updated bank selection and confirm again. No operation was sent.'};
        }
        if (!firmwareBankActionAllowed(current, action, bank) ||
                firmwareBankGuardSignature(firmwareBankState) !== currentSignature) {
            throw {error: 'The selected bank action is no longer permitted. No operation was sent.'};
        }
        const prompt = $(button).attr('data-confirm');
        const consequence = reboot ? '\n' + firmwareRebootPlan(current).explanation : '';
        if (prompt && !window.confirm(prompt + consequence)) {
            $('#firmware-message').text('Cancelled. No bank operation was submitted.');
            return;
        }
        if (reboot) sessionStorage.setItem(jobKey() + '-reboot', '1');
        else sessionStorage.removeItem(jobKey() + '-reboot');
        submitted = true;
        $('#firmware-message').text('Submitting bank operation after fresh verification.');
        const values = {action: action, state_guard: current.state_guard};
        if (bank) values.bank = bank;
        const record = await post8311('firmware', values);
        $('#firmware-message').text('Bank job accepted. ' +
            (reboot ? 'A disconnect is expected if the checked reboot proceeds.' : ''));
        monitorJob(record);
    } catch (error) {
        if (!liveCheckSucceeded) updateBankState(null);
        $('#firmware-message').text(errorMessage(error) +
            ' Review the bank status before another operation.');
        if (reboot && submitted && !error._httpStatus) recoverBankAfterReboot();
        else if (reboot) sessionStorage.removeItem(jobKey() + '-reboot');
    } finally {
        if (!currentJob || !['queued','running','cancel_requested'].includes(currentJob.state)) {
            firmwareBusy = false;
            if (submitted) refreshFirmwareState();
        }
        refreshFirmwareControls();
    }
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
                if (!verifiedBankSnapshot(state)) {
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
                updateBankState(null);
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
	const tokenField = document.querySelector('input[name="token"]');
	const defaults = {};
	defaults['token'] = tokenField ? tokenField.value : '';
	const body = new URLSearchParams(Object.assign(defaults, values));
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
/* C-011: one-shot authenticated read-only effective management comparison.
 * Never poll automatically, send settings, or mistake UCI-only data for a
 * verified live service. All device-supplied strings use textContent. */
/* C-011 system/SFP: manual, authenticated read-only comparison.
 * UCI SFP values are NOT independently measured host EEPROM bytes. */
/* C-011 noncredential PON/OMCI: one manual admin GET, no writer.
 * O5.1 is an independent optical association observation, NOT proof
 * that the four configured values were consumed or that WAN is working.
 * Never render raw native status, PON identity, authentication or HTML. */
/* C-011 ISP VLAN: explicit authenticated read-only GET.
 * A daemon PID, source default or historical reconciler receipt is NOT
 * independent proof of current TC rules or subscriber Internet service. */
function refreshVlanEffective() {
    const panel=document.getElementById('aott-vlan-effective');
    const button=document.getElementById('aott-vlan-effective-refresh');
    const status=document.getElementById('aott-vlan-effective-status');
    const results=document.getElementById('aott-vlan-effective-results');
    if (!panel || !button || !status || !results) return;
    const url=panel.getAttribute('data-effective-url') || '';
    if (!url.startsWith('/') || url.startsWith('//')) {
        status.textContent='The local read-only VLAN endpoint is invalid.';
        return;
    }
    button.disabled=true;
    status.textContent='Reading VLAN configuration and last reconciliation. No settings will be changed.';
    results.hidden=true;
    results.textContent='';
    request8311(url,{method:'GET',cache:'no-store'}).then(record => {
        if (record.success!==true || !record.data || record.data.schema!==1 ||
            record.data.no_device_write!==true ||
            record.data.contains_registration_secret!==false ||
            record.data.source_only_not_hardware_qualified!==true ||
            !record.data.fields || !record.data.last_reconciliation ||
            !record.data.daemon || !record.data.summary || !record.data.kernel_tc) {
            throw {error:'Incomplete VLAN read-only response.'};
        }
        const names=[
            ['fix_vlans','VLAN translation mode'],
            ['internet_vlan','Local Internet VLAN'],
            ['services_vlan','Local services VLAN']
        ];
        const table=document.createElement('table');
        table.className='table';
        const heading=document.createElement('tr');
        ['Setting','Saved override','Source default','Last recorded reconciliation','Current-effect evidence'].forEach(label => {
            const cell=document.createElement('th');
            cell.textContent=label;
            heading.appendChild(cell);
        });
        table.appendChild(heading);
        const shown=(value,fallback) =>
            typeof value==='string' && value.length ? value : fallback;
        names.forEach(([id,label]) => {
            const field=record.data.fields[id];
            if (!field || field.id!==id ||
                (field.runtime_effect_proven!==true &&
                 field.runtime_effect_proven!==false) ||
                field.hardware_qualified!==false) {
                throw {error:'Incomplete VLAN evidence for '+id};
            }
            if (field.runtime_effect_proven===true &&
                (record.data.kernel_tc.full_owned_rules_match!==true ||
                 field.observed_source!=='independent_kernel_tc_flower_readback' ||
                 typeof field.observed_effective_value!=='string')) {
                throw {error:'Unsupported claim of verified live VLAN rules'};
            }
            const row=document.createElement('tr');
            let evidence='Live traffic-control rules not independently verified';
            if (field.runtime_effect_proven===true) {
                evidence='Installed built-in kernel TC selectors match; forwarding and Internet unverified';
            } else if (field.last_recorded_value!=null) {
                evidence=field.saved_to_last_recorded==='mismatch'
                    ? 'Saved override differs from historical record; selected TC proof unavailable'
                    : field.saved_to_last_recorded==='match'
                      ? 'Saved/recorded match; live TC still unverified'
                      : 'Historical record available; effective rules unverified';
            }
            [label,shown(field.saved_value,'(unset or unavailable)'),
             shown(field.source_default,'(not specified)'),
             shown(field.last_recorded_value,'(not recorded)'),
             evidence].forEach(value => {
                const cell=document.createElement('td');
                cell.textContent=value;
                row.appendChild(cell);
            });
            table.appendChild(row);
        });
        const meta=document.createElement('p');
        const last=record.data.last_reconciliation;
        const daemon=record.data.daemon;
        const daemonText=daemon.running===true?'running'
            :daemon.running===false?'not found':'unknown';
        const hashText=last.topology_matches_record===true
            ?'same as last recorded topology'
            :last.topology_matches_record===false
              ?'changed since last record':'not verified';
        const tc=record.data.kernel_tc;
        const tcText=tc.full_owned_rules_match===true
            ? 'selected built-in kernel rules independently matched ('+
              String(tc.verified_rules_count||0)+' selectors)'
            : tc.read_attempted===true
              ? 'attempted but no complete match'
              : 'not verified';
        meta.textContent='VLAN daemon: '+daemonText+
            '. Last validated native receipt: '+
            (last.present===true?'present':'absent or unverified')+
            '. Topology comparison: '+hashText+
            '. Native read-only TC verification: '+tcText+
            '. An unchanged topology or daemon alone proves nothing about current TC rules. Even a selected-rule match does not prove all rules, hardware forwarding, ISP service mapping or Internet connectivity.';
        results.appendChild(meta);
        results.appendChild(table);
        results.hidden=false;
        status.textContent='Read-only VLAN comparison complete. No settings changed.';
    }).catch(error => {
        results.hidden=true;
        results.textContent='';
        status.textContent='Readback unavailable: '+errorMessage(error)+
            ' No settings changed.';
    }).finally(() => { button.disabled=false; });
}
function refreshPonEffective() {
    const panel=document.getElementById('aott-pon-effective');
    const button=document.getElementById('aott-pon-effective-refresh');
    const status=document.getElementById('aott-pon-effective-status');
    const results=document.getElementById('aott-pon-effective-results');
    if (!panel || !button || !status || !results) return;
    const url=panel.getAttribute('data-effective-url') || '';
    if (!url.startsWith('/') || url.startsWith('//')) {
        status.textContent='The local PON read-only endpoint is invalid.';
        return;
    }
    button.disabled=true;
    status.textContent='Checking configured PON values and registration. No settings will be changed.';
    results.hidden=true;
    results.textContent='';
    request8311(url,{method:'GET',cache:'no-store'}).then(record => {
        if (record.success!==true || !record.data || record.data.schema!==1 ||
            record.data.no_device_write!==true ||
            record.data.contains_registration_secret!==false ||
            record.data.source_only_not_hardware_qualified!==true ||
            !record.data.fields || !record.data.registration ||
            !record.data.summary) {
            throw {error:'Incomplete noncredential PON status response.'};
        }
        const list=[
            ['pon_mode','Optical access mode'],
            ['omcc_version','OMCI channel version'],
            ['iop_mask','OMCI interoperability mask'],
            ['mib_file','OMCI MIB profile']
        ];
        const table=document.createElement('table');
        table.className='table';
        const top=document.createElement('tr');
        ['Setting','Saved override','Vendor configuration','Effective-state evidence'].forEach(title => {
            const cell=document.createElement('th');
            cell.textContent=title;
            top.appendChild(cell);
        });
        table.appendChild(top);
        const printable=(v,fallback) =>
            typeof v==='string' && v.length ? v : fallback;
        list.forEach(([key,label]) => {
            const field=record.data.fields[key];
            if (!field || field.id!==key || field.runtime_effect_proven!==false ||
                field.hardware_qualified!==false) {
                throw {error:'Incomplete or unqualified PON field: '+key};
            }
            const line=document.createElement('tr');
            let evidence='OMCI runtime effect unverified';
            if (field.configured_value==null) {
                evidence='Vendor configuration unavailable';
            } else if (field.saved_to_configured==='mismatch') {
                evidence='Saved value differs from UCI; OMCI effect unverified';
            } else if (field.saved_to_configured==='match') {
                evidence='Saved/UCI match; OMCI effect unverified';
            }
            [label,
             printable(field.saved_value,'(unset or unavailable)'),
             printable(field.configured_value,'(not available)'),
             evidence].forEach(value => {
                const cell=document.createElement('td');
                cell.textContent=value;
                line.appendChild(cell);
            });
            table.appendChild(line);
        });
        const code=record.data.registration.state;
        if (!(code==null || (Number.isInteger(code) && code>=0 && code<=255))) {
            throw {error:'PON registration state was not verified.'};
        }
        const note=document.createElement('p');
        note.textContent=code==null
            ? 'PON state: unavailable. Do not infer Internet connectivity.'
            : code===51
              ? 'PON state: O5.1 associated. This does not prove ISP Internet connectivity or individual OMCI setting effects.'
              : 'PON state: '+String(code)+'. Not O5.1. Internet connectivity remains unverified.';
        results.appendChild(note);
        results.appendChild(table);
        results.hidden=false;
        status.textContent='Read-only PON/OMCI comparison complete. No settings changed.';
    }).catch(error => {
        results.hidden=true;
        results.textContent='';
        status.textContent='Readback unavailable: '+errorMessage(error)+
            ' No settings changed.';
    }).finally(() => { button.disabled=false; });
}
function refreshDeviceEffective() {
    const panel=document.getElementById('aott-device-effective');
    const button=document.getElementById('aott-device-effective-refresh');
    const status=document.getElementById('aott-device-effective-status');
    const results=document.getElementById('aott-device-effective-results');
    if (!panel || !button || !status || !results) return;
    const url=panel.getAttribute('data-effective-url') || '';
    if (!url.startsWith('/') || url.startsWith('//')) {
        status.textContent='The local read-only endpoint is invalid.';
        return;
    }
    button.disabled=true;
    status.textContent='Reading device and virtual SFP configuration. No settings will be changed.';
    results.hidden=true;
    results.textContent='';
    request8311(url,{method:'GET',cache:'no-store'}).then(record => {
        if (record.success!==true || !record.data || record.data.schema!==1 ||
            record.data.no_device_write!==true ||
            record.data.source_only_not_hardware_qualified!==true ||
            !record.data.fields || !record.data.summary) {
            throw {error:'Incomplete device and SFP readback.'};
        }
        const fieldList=[
            ['hostname','System hostname'],
            ['lang','LuCI language'],
            ['timezone','Time zone'],
            ['ntp_servers','NTP servers'],
            ['sfp_vendor','Host-visible SFP vendor'],
            ['sfp_oui','Host-visible SFP vendor OUI'],
            ['sfp_partno','Host-visible SFP part number'],
            ['sfp_rev','Host-visible SFP revision'],
            ['sfp_serial','Host-visible SFP serial'],
            ['sfp_date','Host-visible SFP date code'],
            ['sfp_vendordata','Host-visible SFP vendor data']
        ];
        const table=document.createElement('table');
        table.className='table';
        const heading=document.createElement('tr');
        ['Setting','Saved override','Configured','Observed running value','Evidence'].forEach(label => {
            const cell=document.createElement('th');
            cell.textContent=label;
            heading.appendChild(cell);
        });
        table.appendChild(heading);
        const show=(value,empty) =>
            typeof value==='string' && value.length ? value : empty;
        fieldList.forEach(([id,title]) => {
            const field=record.data.fields[id];
            if (!field || field.id!==id) throw {error:'Incomplete device field: '+id};
            const line=document.createElement('tr');
            let proof='No independent runtime proof';
            if (field.runtime_effect_proven===true) {
                proof=field.saved_to_observed==='match'
                    ? 'Kernel value matches saved'
                    : field.saved_to_observed==='mismatch'
                    ? 'Kernel value differs from saved'
                    : 'Kernel value observed; saved comparison unavailable';
            } else if (id.startsWith('sfp_') && field.configured_value!==null) {
                proof='Virtual EEPROM configured; host presentation unverified';
            } else if (id==='ntp_servers' && field.configured_value!==null) {
                proof='NTP servers configured; synchronization unverified';
            } else if (field.configured_value!==null) {
                proof='Configured only; running effect unverified';
            }
            [title,show(field.saved_value,'(unset or unavailable)'),
             show(field.configured_value,'(not available)'),
             show(field.observed_value,'(not independently observed)'),
             proof].forEach(value => {
                const cell=document.createElement('td');
                cell.textContent=value;
                line.appendChild(cell);
            });
            table.appendChild(line);
        });
        const info=document.createElement('p');
        info.textContent='Fields observed in running kernel: '+
            String(record.data.summary.observed_runtime||0)+
            '. No virtual SFP host EEPROM or time-sync status is inferred.';
        results.appendChild(info);
        results.appendChild(table);
        results.hidden=false;
        status.textContent='Read-only device and SFP comparison complete. No settings changed.';
    }).catch(error => {
        results.hidden=true;
        results.textContent='';
        status.textContent='Readback unavailable: '+errorMessage(error)+
            ' No settings changed.';
    }).finally(() => { button.disabled=false; });
}
function refreshManagementEffective() {
    const panel=document.getElementById('aott-management-effective');
    const button=document.getElementById('aott-management-effective-refresh');
    const status=document.getElementById('aott-management-effective-status');
    const results=document.getElementById('aott-management-effective-results');
    if (!panel || !button || !status || !results) return;
    const url=panel.getAttribute('data-effective-url') || '';
    if (!url.startsWith('/') || url.startsWith('//')) {
        status.textContent='The local read-only URL is invalid.';
        return;
    }
    button.disabled=true;
    status.textContent='Reading current management values. No settings will be changed.';
    results.hidden=true;
    results.textContent='';
    request8311(url, {method:'GET',cache:'no-store'}).then(record => {
        if (record.success!==true || !record.data || record.data.schema!==1 ||
            !record.data.fields || !record.data.summary ||
            record.data.no_device_write!==true) {
            throw {error:'Incomplete read-only management response.'};
        }
        const fieldList=[
            ['ipaddr','Management IPv4'],
            ['netmask','Subnet mask'],
            ['gateway','Management gateway'],
            ['dns_server','DNS server'],
            ['pingd','Management keepalive enabled'],
            ['ping_ip','Keepalive destination'],
            ['lct_mac','Management MAC'],
            ['reverse_arp','Reverse ARP enabled'],
            ['https_redirect','HTTP to HTTPS redirect']
        ];
        const table=document.createElement('table');
        table.className='table';
        const heading=document.createElement('tr');
        ['Setting','Saved override','Configured','Running observation','Verification'].forEach(title => {
            const cell=document.createElement('th');
            cell.textContent=title;
            heading.appendChild(cell);
        });
        table.appendChild(heading);
        const valueText=(value,blank) => {
            if (typeof value==='string' && value.length) return value;
            return blank;
        };
        fieldList.forEach(([id,label]) => {
            const field=record.data.fields[id];
            if (!field || field.id!==id) throw {error:'Missing management field: '+id};
            const line=document.createElement('tr');
            const observed=field.observed_source==='kernel_no_management_default_route'
                ? '(no management default route)'
                : valueText(field.observed_value,'(not observed)');
            let verification='Not independently verified';
            if (field.runtime_effect_proven===true) {
                verification=field.saved_to_observed==='match'
                    ? 'Running value observed; matches saved'
                    : field.saved_to_observed==='mismatch'
                    ? 'Running value observed; differs from saved'
                    : 'Running value observed; saved comparison unavailable';
            } else if (field.configured_value!==null) {
                verification='Configuration found; running effect unverified';
            }
            [label,
             valueText(field.saved_value,'(default or unavailable)'),
             valueText(field.configured_value,'(not available)'),
             observed,verification].forEach(value => {
                const cell=document.createElement('td');
                cell.textContent=value;
                line.appendChild(cell);
            });
            table.appendChild(line);
        });
        const intro=document.createElement('p');
        intro.textContent='Management path: '+
            valueText(record.data.management_section,'undetermined')+
            '. Interface: '+valueText(record.data.management_interface,'undetermined')+
            '. Kernel-observed fields: '+
            String(record.data.summary.kernel_observed||0)+
            '. Saved values alone do not prove active service.';
        results.appendChild(intro);
        results.appendChild(table);
        results.hidden=false;
        status.textContent='Read-only management comparison complete. No settings changed.';
    }).catch(error => {
        results.hidden=true;
        results.textContent='';
        status.textContent='Readback unavailable: '+errorMessage(error)+
            ' No settings changed.';
    }).finally(() => { button.disabled=false; });
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
    if (!base || !base.startsWith('/') || base.startsWith('//') ||
            /[?#\\\s]/.test(base) || !/\/admin\/8311\/pon_dump$/.test(base)) {
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
    if (!verifiedBankSnapshot(state)) {
        firmwareBankState = null;
        firmwareBankStateVerifiedAt = 0;
        $('#bank-active,#bank-committed,#bank-pending,#bank-contract').text('unknown');
        $('#bank-receipts').text('Live bank state unavailable.');
        $('#receipt-A,#receipt-B,#valid-A,#valid-B').text('unknown');
        const plan = firmwareRebootPlan(null);
        $('#bank-next-reboot').text(plan.next);
        $('#bank-recovery').text(plan.recovery);
        $('#bank-explanation').text(plan.explanation);
        refreshFirmwareControls();
        return;
    }
    firmwareBankState = state;
    firmwareBankStateVerifiedAt = Date.now();
	$('#bank-active').text(state.active || 'unknown'); $('#bank-committed').text(state.committed || 'unknown');
	$('#bank-pending').text(state.pending || 'none'); $('#bank-contract').text(state.boot_contract === true ? 'verified' : 'unknown');
	$('#bank-receipts').text(JSON.stringify(state.banks || {}, null, 2));
    const plan = firmwareRebootPlan(state);
    $('#bank-next-reboot').text(plan.next);
    $('#bank-recovery').text(plan.recovery);
    $('#bank-explanation').text(plan.explanation);
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
async function submitCheckedFirmwareInstall(button, selection) {
    if (!button || button.disabled || firmwareBusy || !selection ||
            !firmwareBankStateFresh()) return;
    const observed = firmwareBankGuardSignature(firmwareBankState);
    const preview = firmwareInstallImpact(firmwareBankState);
    if (!observed || !preview.ready) return;
    const selectedId = selection.value;
    const selectedSha256 = selection.dataset.sha256;
    firmwareBusy = true;
    refreshFirmwareControls();
    $('#firmware-message').text(
        'Refreshing bank selection before confirming the inactive-bank overwrite.');
    try {
        const fresh = await request8311('bank_status');
        if (!verifiedBankSnapshot(fresh)) {
            updateBankState(null);
            throw {error: 'Live firmware bank status is not verified. No installation was sent.'};
        }
        const fingerprint = firmwareBankGuardSignature(fresh);
        updateBankState(fresh);
        const consequence = firmwareInstallImpact(fresh);
        if (fingerprint !== observed || consequence.target !== preview.target) {
            throw {error: 'The inactive bank or firmware receipts changed. ' +
                'Review the current bank state and choose the upload again. ' +
                'No installation was sent.'};
        }
        if (!consequence.ready) {
            throw {error: 'A pending or running firmware trial prevents installation.'};
        }
        const currentSelection = document.querySelector(
            'input[name="upload-selection"]:checked');
        if (currentSelection !== selection ||
                currentSelection.value !== selectedId ||
                currentSelection.dataset.sha256 !== selectedSha256) {
            throw {error: 'The selected upload changed. No installation was sent.'};
        }
        const prompt = $(button).attr('data-confirm') || 'Install this archive?';
        if (!window.confirm(prompt + '\n' + consequence.explanation)) {
            $('#firmware-message').text('Installation cancelled. No firmware was written.');
            return;
        }
        // The installer itself independently verifies active/committed bank
        // selection and flash locks; the browser warning is not a substitute.
        const record = await post8311('firmware', {
            action: 'install', upload_id: selectedId, sha256: selectedSha256,
            expected_active: fresh.active, expected_target: consequence.target,
            state_guard: fresh.state_guard
        });
        $('#firmware-message').text(
            'Firmware installation job accepted. Verify its progress and bank receipts.');
        monitorJob(record);
    } catch (error) {
        $('#firmware-message').text(errorMessage(error) +
            ' Inspect current bank state before any new installation request.');
    } finally {
        if (!currentJob || !['queued','running','cancel_requested'].includes(currentJob.state)) {
            firmwareBusy = false;
            refreshFirmwareState();
        }
        refreshFirmwareControls();
    }
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
    $('#aott-management-effective-refresh').on('click',function(event) {
        event.preventDefault();
        refreshManagementEffective();
    });
    $('#aott-device-effective-refresh').on('click',function(event) {
        event.preventDefault();
        refreshDeviceEffective();
    });
    $('#aott-pon-effective-refresh').on('click',function(event) {
        event.preventDefault();
        refreshPonEffective();
    });
    $('#aott-vlan-effective-refresh').on('click',function(event) {
        event.preventDefault();
        refreshVlanEffective();
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
        submitCheckedFirmwareBankAction(this);
    });
	$('.firmware-artifact').on('click', function() {
		const selection = document.querySelector('input[name="upload-selection"]:checked');
		if (!selection) { $('#firmware-message').text('Select an upload first.'); return; }
        if (this.dataset.action === 'install') {
            submitCheckedFirmwareInstall(this, selection);
            return;
        }
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
            refreshFirmwareControls();
            if (!firmwareBusy && !(currentJob &&
                    ['queued','running','cancel_requested'].includes(currentJob.state))) {
                refreshFirmwareState();
            }
        }, 30000);
        window.addEventListener('pagehide', () => { if (firmwareStatusTimer) clearInterval(firmwareStatusTimer); });
    }
    if ($('#job-panel').length) { const id = sessionStorage.getItem(jobKey()); if (id) pollJob(id); }
});
