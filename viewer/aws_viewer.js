var hardwareReq   = "/json.htm?type=command&param=gethardware";
var tempReq       = "/json.htm?type=command&param=graph&sensor=temp&range=day&idx=";
var tempName      = "/json.htm?type=command&param=getdevices&filter=temp&order=Name";
var switchReq = "/json.htm?type=command&param=getlightlog&range=day&idx=";
var switchName    = "/json.htm?type=command&param=getdevices&filter=lightlog&order=Name";
var devicesReq    = "/json.htm?type=command&param=getdevices";
var PercentageReq = "/json.htm?type=command&param=graph&sensor=Percentage&range=day&idx=";
var utilityReq    = "/json.htm?type=command&param=graph&sensor=counter&range=day&idx=";
var windReq       = "/json.htm?type=command&param=graph&sensor=wind&range=day&idx=";
var setpointReq   = "/json.htm?type=command&param=getdevices&rid=";
var settingsReg   = "/json.htm?type=command&param=getsettings";
var rainReq = "/json.htm?type=command&param=graph&sensor=rain&range=day&idx=";


if (typeof window.OntozoKontroller === 'undefined') {
	class OntozoKontroller {
		constructor() {
			this.name = "";
			this.ontozokapcs = undefined;
			this.soilmoisture = undefined;
		}
	}
	window.OntozoKontroller = OntozoKontroller;
}

if (typeof window.Ontozo === 'undefined') {
	class Ontozo {
		constructor() {
			this.historic=undefined;
			this.isDimmer=false;
		}
	}
	window.Ontozo = Ontozo;
}

Date.prototype.yyyymmdd_hhmm = function() {
	var mm = this.getMonth() + 1; // getMonth() is zero-based
	var dd = this.getDate();
	var hh = this.getHours();
	var mm = this.getMinutes();

	return [this.getFullYear(),
		(mm>9 ? '' : '0') + mm,
		(dd>9 ? '' : '0') + dd,
		'_',
		(hh>9 ? '' : '0') + hh,
		(mm>9 ? '' : '0') + mm
		].join('');
};

function getRequestParam(name){
	var req = location.search;
	if(req.length == 0) {
		req = location.href;
	}
	if(name=(new RegExp('[?&]'+encodeURIComponent(name)+'=([^&]*)')).exec(req))
		return decodeURIComponent(name[1]);
}

class IrrigationSwitch {
	constructor() {
		this.historic = [];
	}
}

function getOntozo() {
	nodata = true;
	var langakt = "en"; // Alapértelmezett nyelv
	var request = proto + address + ":" + port.toString() + hardwareReq;
	var ontozook = [];
	$.ajax({
		url: request,
		async: false,
		success: function (result) {
			for (var i = 0; i < result.result.length; i++) {
				if (result.result[i].Extra == "AWS_OA" && result.result[i].Enabled == "true") {
					nodata = false;
					var ontozo = new Ontozo();
					var name = result.result[i].Name;
					ontozo.name = name;
					ontozo.id = result.result[i].idx;
					var minDate = 0;
					var innerRequest = proto + address + ":" + port.toString() + devicesReq;
					$.ajax({
						url: innerRequest,
						async: false,
						success: function (resultOntozo) {
							ontozo.host = result.result[i].Address
							ontozo.uname = result.result[i].Username
							ontozo.pass = result.result[i].Password
							ontozo.port = result.result[i].Port
							for (var j = 0; j < resultOntozo.result.length; j++) {
								if (ontozo.id == resultOntozo.result[j].HardwareID && resultOntozo.result[j].Unit == 12) {
									request = proto + address + ":" + port.toString() + PercentageReq + resultOntozo.result[j].idx;
									//console.log(request);
									$.ajax({
										url: request,
										async: false,
										success: function (resultSoilMoisture) {
											ontozo.soilmoisture = resultSoilMoisture.result;
										}
									});
								}

								if (ontozo.id == resultOntozo.result[j].HardwareID && resultOntozo.result[j].Unit == 10) {
									request = proto + address + ":" + port.toString() + PercentageReq + resultOntozo.result[j].idx;
									//console.log(request);
									$.ajax({
										url: request,
										async: false,
										success: function (resultLast24) {
											ontozo.last24 = resultLast24.result;
										}
									});
								}

								if (ontozo.id == resultOntozo.result[j].HardwareID && resultOntozo.result[j].Unit == 11) {
									request = proto + address + ":" + port.toString() + PercentageReq + resultOntozo.result[j].idx;
									//console.log(request);
									$.ajax({
										url: request,
										async: false,
										success: function (resultNext24) {
											ontozo.next24 = resultNext24.result;
										}
									});
								}

								if (ontozo.id == resultOntozo.result[j].HardwareID && resultOntozo.result[j].Unit == 9) {
									request = proto + address + ":" + port.toString() + switchReq + resultOntozo.result[j].idx;
									//console.log(request);
									$.ajax({
										url: request,
										async: false,
										success: function (resultIrrigationSwitch) {

											var minDate = Date.now() - (27 * 60 * 60 * 1000);

											if (!resultIrrigationSwitch || !Array.isArray(resultIrrigationSwitch.result)) {
												return;
											}

											ontozo.irrigationswitch = resultIrrigationSwitch.result
												.filter(item => new Date(item.Date).getTime() >= minDate)
												.sort((a, b) => new Date(a.Date).getTime() - new Date(b.Date).getTime());

											lastState = resultIrrigationSwitch.result
												.sort((a, b) => new Date(a.Date).getTime() - new Date(b.Date).getTime())
												.slice(-1)[0];

											lastStateDate = new Date(lastState.Date).getTime();

											if (lastStateDate < minDate && lastState.Status === "On") {
												minDateState = {
													...lastState,
													Date: new Date(minDate).toISOString()
												};

												ontozo.irrigationswitch.unshift(minDateState);

												currentTime = Date.now();

												currentState = {
													...lastState,
													Date: new Date(currentTime).toISOString()
												};

												ontozo.irrigationswitch.push(currentState);
											}
										}
									});
								}
							}
						}
					});
					ontozook.push(ontozo);
				}
			}
		}
	});
	//console.log("ontozook", ontozook);
	return ontozook;
}



