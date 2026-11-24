const searchInput = document.querySelector("#recipe-search");
const tagButtons = [...document.querySelectorAll(".tag-cloud-item")];
const cards = [...document.querySelectorAll(".recipe-card")].map((element) => ({
  element,
  search: element.dataset.search.toLocaleLowerCase(element.lang || undefined),
  tags: JSON.parse(element.dataset.tags),
}));
const params = new URLSearchParams(window.location.search);
let activeTag = params.get("tag") || "";

function updateRecipes() {
  const query = searchInput.value.trim().toLocaleLowerCase();
  for (const card of cards) {
    card.element.hidden =
      !card.search.includes(query) ||
      Boolean(activeTag && !card.tags.includes(activeTag));
  }
  for (const button of tagButtons) {
    const active = button.dataset.tag === activeTag;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

for (const button of tagButtons) {
  button.addEventListener("click", () => {
    activeTag = activeTag === button.dataset.tag ? "" : button.dataset.tag;
    updateRecipes();
  });
}
searchInput.addEventListener("input", updateRecipes);

for (const element of document.querySelectorAll("[data-requires-js]")) {
  element.hidden = false;
}
updateRecipes();
