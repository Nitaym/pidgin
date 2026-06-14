/** Common American first names for default agent display names at hire. */

export type AgentGender = "" | "female" | "male";

const MALE_NAMES = [
  "James", "Robert", "John", "Michael", "David", "William", "Richard",
  "Joseph", "Thomas", "Charles", "Christopher", "Daniel", "Matthew",
  "Anthony", "Mark", "Donald", "Steven", "Paul", "Andrew", "Joshua",
  "Kenneth", "Kevin", "Brian", "George", "Timothy", "Ronald", "Edward",
  "Jason", "Jeffrey", "Ryan", "Jacob", "Gary", "Nicholas", "Eric",
  "Jonathan", "Stephen", "Larry", "Justin", "Scott", "Brandon", "Benjamin",
  "Samuel", "Gregory", "Alexander", "Patrick", "Frank", "Raymond", "Jack",
  "Dennis", "Jerry", "Tyler", "Aaron", "Henry", "Adam", "Nathan", "Zachary",
  "Douglas", "Peter", "Kyle", "Noah", "Ethan", "Jeremy", "Walter",
  "Christian", "Keith", "Roger", "Terry", "Austin", "Sean", "Gerald",
  "Carl", "Harold", "Dylan", "Arthur", "Lawrence", "Jesse", "Bryan",
  "Billy", "Bruce", "Gabriel", "Joe", "Logan", "Alan", "Juan", "Wayne",
  "Roy", "Ralph", "Randy", "Eugene", "Vincent", "Russell", "Louis",
  "Philip", "Bobby", "Johnny", "Bradley",
] as const;

const FEMALE_NAMES = [
  "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan",
  "Jessica", "Sarah", "Karen", "Lisa", "Nancy", "Betty", "Margaret",
  "Sandra", "Ashley", "Kimberly", "Emily", "Donna", "Michelle", "Carol",
  "Amanda", "Melissa", "Deborah", "Stephanie", "Rebecca", "Sharon", "Laura",
  "Cynthia", "Kathleen", "Amy", "Angela", "Shirley", "Anna", "Brenda",
  "Pamela", "Emma", "Nicole", "Helen", "Samantha", "Katherine", "Christine",
  "Debra", "Rachel", "Carolyn", "Janet", "Catherine", "Maria", "Heather",
  "Diane", "Ruth", "Julie", "Olivia", "Joyce", "Virginia", "Victoria",
  "Kelly", "Lauren", "Christina", "Joan", "Evelyn", "Judith", "Megan",
  "Andrea", "Cheryl", "Hannah", "Jacqueline", "Martha", "Gloria", "Teresa",
  "Ann", "Sara", "Madison", "Frances", "Kathryn", "Janice", "Jean",
  "Abigail", "Alice", "Judy", "Sophia", "Grace", "Denise", "Amber",
  "Doris", "Marilyn", "Danielle", "Beverly", "Isabella", "Theresa", "Diana",
  "Natalie", "Brittany", "Charlotte", "Marie", "Kayla", "Alexis",
] as const;

const UNISEX_NAMES = [
  "Alex", "Taylor", "Casey", "Riley", "Morgan", "Jamie", "Quinn", "Avery",
  "Cameron", "Drew", "Skyler", "Parker", "Reese", "Blake", "Hayden",
  "Charlie", "Sam", "Jessie", "Dakota", "Rowan", "Finley", "Emerson",
  "Sawyer", "River", "Phoenix", "Jordan",
] as const;

function pick(names: readonly string[]): string {
  return names[Math.floor(Math.random() * names.length)];
}

/** Random first name matching the agent's configured gender. */
export function randomFirstName(gender: AgentGender = ""): string {
  if (gender === "female") return pick([...FEMALE_NAMES, ...UNISEX_NAMES]);
  if (gender === "male") return pick([...MALE_NAMES, ...UNISEX_NAMES]);
  return pick([...MALE_NAMES, ...FEMALE_NAMES, ...UNISEX_NAMES]);
}

/** True when the name clearly belongs to the other gender's list. */
export function nameMatchesGender(name: string, gender: AgentGender): boolean {
  if (!gender) return true;
  const n = name.trim().toLowerCase();
  if (!n) return true;
  const inUnisex = UNISEX_NAMES.some((x) => x.toLowerCase() === n);
  if (inUnisex) return true;
  const inFemale = FEMALE_NAMES.some((x) => x.toLowerCase() === n);
  const inMale = MALE_NAMES.some((x) => x.toLowerCase() === n);
  if (!inFemale && !inMale) return true; // custom name — user's call
  return gender === "female" ? inFemale : inMale;
}
