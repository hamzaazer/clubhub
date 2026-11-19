// Confirm before destructive actions: <form data-confirm="Are you sure?">
document.addEventListener("submit", function (e) {
  var msg = e.target.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) e.preventDefault();
});

document.addEventListener("DOMContentLoaded", function () {
  var currentPath = window.location.pathname.replace(/\/$/, "") || "/";
  document.querySelectorAll(".top nav a[href]").forEach(function (link) {
    var linkPath = new URL(link.href, window.location.origin).pathname.replace(/\/$/, "") || "/";
    if (linkPath === currentPath) link.setAttribute("aria-current", "page");
  });

  var locationSelects = [
    ["wilaya", "commune", "Select commune"],
    ["filter-wilaya", "filter-commune", "All communes"]
  ];
  if (locationSelects.some(function (ids) {
    return document.getElementById(ids[0]) && document.getElementById(ids[1]);
  })) {
    fetch("/static/dz_locations.json")
      .then(function (response) { return response.json(); })
      .then(function (locations) {
        locationSelects.forEach(function (ids) {
          var wilayaSelect = document.getElementById(ids[0]);
          var communeSelect = document.getElementById(ids[1]);
          if (!wilayaSelect || !communeSelect) return;

          function updateCommunes(selectedCommune) {
            var code = Number(wilayaSelect.value);
            var wilaya = locations.find(function (item) { return item.code === code; });
            communeSelect.replaceChildren(new Option(ids[2], ""));
            if (!wilaya) return;
            wilaya.communes.forEach(function (commune) {
              communeSelect.add(new Option(commune.name, commune.name));
            });
            if (selectedCommune) communeSelect.value = selectedCommune;
          }

          updateCommunes(communeSelect.value);
          wilayaSelect.addEventListener("change", function () { updateCommunes(""); });
        });
      })
      .catch(function () { /* The server-rendered commune options remain available. */ });
  }

  var memberList = document.querySelector("[data-live-members]");
  if (memberList) {
    var listSnapshot = "";
    function renderLiveMembers(members) {
      var snapshot = JSON.stringify(members);
      if (snapshot === listSnapshot) return;
      listSnapshot = snapshot;
      var fragment = document.createDocumentFragment();
      if (!members.length) {
        var empty = document.createElement("p");
        empty.className = "muted";
        empty.textContent = "No members here.";
        fragment.appendChild(empty);
      }
      members.forEach(function (member) {
        var link = document.createElement("a");
        link.className = "item";
        link.href = member.href;

        var row = document.createElement("span");
        row.className = "row";
        var avatar = member.has_image ? document.createElement("img") : document.createElement("span");
        avatar.className = "avatar";
        if (member.has_image) {
          avatar.src = member.avatar_url;
          avatar.alt = "";
          avatar.loading = "lazy";
        } else {
          avatar.textContent = (member.name || "?").charAt(0).toUpperCase();
        }
        row.appendChild(avatar);

        var details = document.createElement("span");
        details.appendChild(document.createTextNode(member.name));
        details.appendChild(document.createElement("br"));
        var summary = document.createElement("small");
        summary.className = "muted";
        summary.textContent = [member.email, member.club_role, member.location].filter(Boolean).join(" · ");
        details.appendChild(summary);
        row.appendChild(details);
        link.appendChild(row);

        var badge = document.createElement("span");
        badge.className = "badge " + ({approved: "ok", pending: "warn", rejected: "bad"}[member.status] || "idle");
        badge.textContent = (member.status || "").replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); });
        link.appendChild(badge);
        fragment.appendChild(link);
      });
      memberList.replaceChildren(fragment);
    }

    function pollMembers() {
      if (document.hidden) return;
      fetch(memberList.dataset.liveUrl, {cache: "no-store"})
        .then(function (response) { if (!response.ok) throw new Error("Refresh failed"); return response.json(); })
        .then(function (data) { renderLiveMembers(data.members || []); })
        .catch(function () {});
    }
    window.setInterval(pollMembers, 3000);
    pollMembers();
  }

  var memberDetails = document.querySelector("[data-live-member]");
  if (memberDetails) {
    function pollMemberDetails() {
      if (document.hidden) return;
      fetch(memberDetails.dataset.liveUrl, {cache: "no-store"})
        .then(function (response) { if (!response.ok) throw new Error("Refresh failed"); return response.json(); })
        .then(function (member) {
          memberDetails.querySelectorAll("[data-live-field]").forEach(function (element) {
            var key = element.dataset.liveField;
            if (Object.prototype.hasOwnProperty.call(member, key) && element.textContent !== member[key]) {
              element.textContent = member[key];
            }
          });
          var status = memberDetails.querySelector("[data-live-status]");
          if (status) {
            status.className = "badge " + ({approved: "ok", pending: "warn", rejected: "bad"}[member.status] || "idle");
            status.textContent = (member.status || "").replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); });
          }
        })
        .catch(function () {});
    }
    window.setInterval(pollMemberDetails, 3000);
    pollMemberDetails();
  }
});
